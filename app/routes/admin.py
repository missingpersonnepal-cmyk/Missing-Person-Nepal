from __future__ import annotations
from app.services.search_providers import serper_status

from pathlib import Path
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import SessionLocal
from ..models import (
    AdminUser, CaseTimeline, Disaster, DiscoveryCandidate, DiscoverySearchTag,
    DiscoverySourceSeed, MissingPerson, NotificationOutbox,
    NotificationSubscription, PersonCaseState, Source, Submission, utcnow,
)
from ..security import hash_password, verify_password
from ..services.discovery import discover_candidates, generate_queries, google_search_url
from ..services.wide_discovery import collect_known_source_scopes, generate_wide_queries, run_wide_discovery
from ..services.search_providers import SearchProviderUnavailable, brave_status
from ..services.candidate_extract import candidate_mentions_multiple_people, extract_candidate_people_names, extract_candidate_prefill
from ..services.candidate_chatgpt_prefill import (
    ChatGPTPrefillParseError,
    build_candidate_chatgpt_prefill_prompt,
    parse_candidate_chatgpt_prefill,
)
from ..services.openai_prefill import (
    OpenAIPrefillError,
    generate_openai_candidate_prefill,
    openai_prefill_status,
)
from ..services.ai_review import build_free_ai_review_prompt, parse_free_ai_review
from ..services.master_records import apply_submission_to_master
from ..services.duplicates import find_duplicates
from ..services.exports import build_csv, build_xlsx
from ..services.files import save_image
from ..services.geo import GeoPoint, geocode, parse_coords, route as geo_route, reverse_geocode
from ..services.source_images import discover_public_post_image, discover_public_post_text, download_public_source_image, is_allowed_public_image_url
from ..services.source_ocr import extract_ocr_text, ocr_available
from ..services.notifications import (
    add_subscription,
    cancel_pending_notifications,
    enqueue_case_notifications,
    mask_destination,
    retry_failed_notifications,
)
from ..services.notifications.messages import CASE_UPDATED, FOUND_ALIVE, IDENTIFIED_DECEASED
from ..services.normalization import affected_location_match, canonicalize_url, detect_platform
from ..services.priority_sources import (
    custom_tag_queries,
    discovered_source_activity,
    normalize_facebook_source_scope,
    priority_manual_searches,
    priority_source_scopes,
    source_url_for_scope,
    user_search_tags,
    user_source_seeds,
)
from ..services.share_cards import build_share_card
from .common import admin_gate, audit, current_admin, next_case_number, parse_date, parse_int, parse_time, render, role_gate

router = APIRouter()
MANUAL_DECK_PATH = Path(__file__).resolve().parents[1] / "static" / "user_manual_bilingual.pptx"

ADMIN_ROLES = {"super_admin", "admin", "reviewer", "data_entry", "read_only"}
ROLE_LABELS = {
    "super_admin": "Super Admin",
    "admin": "Admin",
    "reviewer": "Reviewer",
    "data_entry": "Data Entry",
    "read_only": "Read Only",
}


def _normalize_admin_username(value: str) -> str:
    return "".join(ch for ch in value.strip().casefold() if ch.isalnum() or ch in {"_", "-", "."})


def _valid_admin_email(value: str) -> bool:
    return not value or ("@" in value and "." in value.rsplit("@", 1)[-1])


def _active_super_admin_count(db) -> int:
    return db.scalar(
        select(func.count(AdminUser.id)).where(
            AdminUser.active.is_(True),
            AdminUser.role == "super_admin",
        )
    ) or 0


def _validate_password_pair(password: str, confirmation: str) -> str | None:
    if password != confirmation:
        return "Password confirmation does not match"
    if len(password) < 10:
        return "Password must be at least 10 characters"
    return None


def _normalize_gender(value) -> str | None:
    folded = str(value or "").strip().casefold()
    if folded in {"male", "m", "पुरुष"}:
        return "Male"
    if folded in {"female", "f", "महिला"}:
        return "Female"
    return None


def _exact_name_matches(db, disaster_id: int, name: str) -> list[MissingPerson]:
    folded = name.strip().casefold()
    if not folded:
        return []
    return list(db.scalars(
        select(MissingPerson).where(
            MissingPerson.disaster_id == disaster_id,
            MissingPerson.archived.is_(False),
            or_(
                func.lower(func.trim(MissingPerson.name)) == folded,
                func.lower(func.trim(MissingPerson.name_ne)) == folded,
            ),
        )
    ).all())


def _exact_published_name_matches(
    db, disaster_id: int, name: str
) -> list[MissingPerson]:
    return [
        person for person in _exact_name_matches(db, disaster_id, name)
        if person.published
    ]


def _pending_name_matches(db, disaster_id: int, name: str) -> list[Submission]:
    folded = name.strip().casefold()
    if not folded:
        return []
    submissions = db.scalars(
        select(Submission).where(
            Submission.disaster_id == disaster_id,
            Submission.status == "pending",
        )
    ).all()
    return [
        item for item in submissions
        if (item.name or "").strip().casefold() == folded
    ]


PERSON_CASE_STATUSES = {"missing", "found", "identified"}


def _next_discovery_review_url(db, candidate: DiscoveryCandidate, message: str | None = None) -> str:
    next_candidate = db.scalar(
        select(DiscoveryCandidate)
        .where(
            DiscoveryCandidate.id != candidate.id,
            DiscoveryCandidate.disaster_id == candidate.disaster_id,
            DiscoveryCandidate.platform == candidate.platform,
            DiscoveryCandidate.status.in_(["new", "needs_ai", "relevant"]),
        )
        .order_by(DiscoveryCandidate.found_at.desc())
    )
    if next_candidate:
        return f"/admin/discovery/{next_candidate.id}"
    suffix = "&queue_complete=1" if message else ""
    return f"/admin/discovery?disaster_id={candidate.disaster_id}&platform={candidate.platform}{suffix}"


def _source_handled_names(db, candidate: DiscoveryCandidate) -> set[str]:
    submission_names = db.scalars(
        select(Submission.name).where(
            Submission.disaster_id == candidate.disaster_id,
            Submission.social_url == candidate.url,
            or_(
                Submission.status != "rejected",
                Submission.kind == "discovery_skipped",
            ),
        )
    ).all()
    person_names = db.scalars(
        select(MissingPerson.name)
        .join(Source, Source.person_id == MissingPerson.id)
        .where(
            MissingPerson.disaster_id == candidate.disaster_id,
            MissingPerson.archived.is_(False),
            Source.url == candidate.url,
        )
    ).all()
    return {
        (name or "").strip().casefold()
        for name in [*submission_names, *person_names]
        if name
    }


def _remaining_source_names(db, candidate: DiscoveryCandidate, source_post_text: str = "", ocr_text: str = "") -> list[str]:
    detected = extract_candidate_people_names(candidate, source_text=source_post_text, ocr_text=ocr_text)
    handled = _source_handled_names(db, candidate)
    return [name for name in detected if name.strip().casefold() not in handled]


def _person_case_status_map(db, person_ids: list[int]) -> dict[int, str]:
    if not person_ids:
        return {}
    rows = db.scalars(
        select(PersonCaseState).where(PersonCaseState.person_id.in_(person_ids))
    ).all()
    status_map = {row.person_id: row.status for row in rows}
    return {person_id: status_map.get(person_id, "missing") for person_id in person_ids}


def _set_person_case_status(
    db,
    person: MissingPerson,
    status: str,
    note: str | None = None,
) -> PersonCaseState:
    normalized = str(status or "").strip().casefold()
    if normalized not in PERSON_CASE_STATUSES:
        raise ValueError("Invalid person case status")
    state = db.get(PersonCaseState, person.id)
    if state is None:
        state = PersonCaseState(person_id=person.id, status=normalized)
        db.add(state)
    else:
        state.status = normalized
    state.note = str(note or "").strip() or None
    if normalized != "missing":
        # Resolved/deceased cases leave the active public missing-person list.
        person.published = False
    return state


def _add_case_timeline(db, request: Request, person_id: int, event_type: str, note: str | None = None) -> None:
    db.add(CaseTimeline(
        person_id=person_id,
        event_type=event_type,
        actor=str(request.session.get("admin") or "system"),
        note=str(note or "").strip() or None,
    ))


def _source_notes_for_candidate(
    candidate: DiscoveryCandidate,
    source_post_text: str,
    ocr_text: str,
) -> str | None:
    parts: list[str] = []
    if source_post_text:
        parts.append("Public post text:\n" + source_post_text[:12_000])
    elif candidate.snippet:
        parts.append("Search/public snippet:\n" + candidate.snippet)
    if ocr_text:
        parts.append("OCR text from reviewed source image:\n" + ocr_text[:12_000])
    return "\n\n".join(item.strip() for item in parts if item.strip()) or None


def _geo_point_for_text(text: str) -> GeoPoint | None:
    point = parse_coords(text)
    if point:
        return point
    return geocode(text)


def _backfill_published_person_coords(db) -> int:
    """Fill missing coordinates for published cases using last-seen text."""
    updated = 0
    rows = db.scalars(
        select(MissingPerson).where(
            MissingPerson.published.is_(True),
            MissingPerson.archived.is_(False),
            MissingPerson.last_seen_lat.is_(None),
            MissingPerson.last_seen_lon.is_(None),
            MissingPerson.last_seen_location.is_not(None),
        )
    ).all()
    for person in rows:
        point = _geo_point_for_text(person.last_seen_location or "")
        if not point:
            continue
        person.last_seen_lat = point.lat
        person.last_seen_lon = point.lon
        updated += 1
    return updated


@router.get("/admin/geo/reverse")
def admin_geo_reverse(request: Request, lat: float, lon: float):
    gate = admin_gate(request)
    if gate:
        return gate
    label = reverse_geocode(lat, lon)
    return JSONResponse({"label": label or f"{lat}, {lon}"})


@router.get("/admin/geo/route")
def admin_geo_route(request: Request, origin: str, destination: str, mode: str = "driving"):
    gate = admin_gate(request)
    if gate:
        return gate
    try:
        return JSONResponse(geo_route(origin=origin, destination=destination, mode=mode))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.post("/admin/geo/backfill")
def admin_geo_backfill(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        updated = _backfill_published_person_coords(db)
        db.commit()
    return RedirectResponse(f"/admin?geo_backfilled={updated}", status_code=303)


@router.get("/admin/media/{filename}")
def admin_media(request: Request, filename: str):
    gate = admin_gate(request)
    if gate:
        return gate
    if Path(filename).name != filename:
        return HTMLResponse("Not found", status_code=404)
    with SessionLocal() as db:
        referenced = db.scalar(
            select(func.count()).select_from(Submission).where(Submission.photo_path == filename)
        ) or db.scalar(
            select(func.count()).select_from(MissingPerson).where(MissingPerson.photo_path == filename)
        )
        if not referenced:
            return HTMLResponse("Not found", status_code=404)
    path = settings.upload_dir / filename
    if not path.is_file():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path)


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "admin_login.html", error=None)


@router.post("/admin/login", response_class=HTMLResponse)
async def login(request: Request):
    form = await request.form()
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    with SessionLocal() as db:
        admin = db.scalar(select(AdminUser).where(AdminUser.username == username, AdminUser.active.is_(True)))
        if admin is None or not verify_password(password, admin.password_hash):
            return render(request, "admin_login.html", error="Invalid credentials")
        admin.last_login_at = utcnow()
        request.session["admin"] = admin.username
        audit(db, request, "login", "admin", admin.id)
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    with SessionLocal() as db:
        users = list(db.scalars(select(AdminUser).order_by(AdminUser.username)).all())
        return render(request, "admin_users.html", users=users, role_labels=ROLE_LABELS)


@router.get("/admin/users/new", response_class=HTMLResponse)
def admin_user_new(request: Request):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    return render(request, "admin_user_form.html", user=None, error=None, role_labels=ROLE_LABELS)


@router.post("/admin/users/new", response_class=HTMLResponse)
async def admin_user_create(request: Request):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    form = await request.form()
    username = _normalize_admin_username(str(form.get("username") or ""))
    display_name = str(form.get("display_name") or "").strip()
    email = str(form.get("email") or "").strip() or None
    role = str(form.get("role") or "").strip().casefold()
    password = str(form.get("password") or "")
    confirm_password = str(form.get("confirm_password") or "")
    active = str(form.get("active") or "") == "1"
    error = _validate_password_pair(password, confirm_password)
    if not username or not display_name:
        error = "Username and display name are required"
    elif role not in ADMIN_ROLES:
        error = "Invalid role"
    elif not _valid_admin_email(email or ""):
        error = "Invalid email"
    if error:
        return render(request, "admin_user_form.html", user=None, error=error, role_labels=ROLE_LABELS)
    with SessionLocal() as db:
        if db.scalar(select(AdminUser.id).where(AdminUser.username == username)):
            return render(request, "admin_user_form.html", user=None, error="Username already exists", role_labels=ROLE_LABELS)
        user = AdminUser(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            active=active,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
        audit(db, request, "admin_user_created", "admin", user.id, f"role={role}; active={active}")
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_user_edit_page(request: Request, user_id: int):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    with SessionLocal() as db:
        user = db.get(AdminUser, user_id)
        if user is None:
            return HTMLResponse("Not found", status_code=404)
        return render(request, "admin_user_form.html", user=user, error=None, role_labels=ROLE_LABELS)


@router.post("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def admin_user_edit(request: Request, user_id: int):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    form = await request.form()
    display_name = str(form.get("display_name") or "").strip()
    email = str(form.get("email") or "").strip() or None
    role = str(form.get("role") or "").strip().casefold()
    active = str(form.get("active") or "") == "1"
    if not display_name or role not in ADMIN_ROLES or not _valid_admin_email(email or ""):
        with SessionLocal() as db:
            user = db.get(AdminUser, user_id)
            return render(request, "admin_user_form.html", user=user, error="Invalid user details", role_labels=ROLE_LABELS)
    with SessionLocal() as db:
        user = db.get(AdminUser, user_id)
        actor = current_admin(db, request)
        if user is None or actor is None:
            return HTMLResponse("Not found", status_code=404)
        final_super = user.role == "super_admin" and _active_super_admin_count(db) <= 1
        if final_super and (role != "super_admin" or not active):
            return HTMLResponse("Cannot disable or demote the final active Super Admin", status_code=409)
        if user.id == actor.id and not active:
            return HTMLResponse("Cannot disable your own active account", status_code=409)
        old_role = user.role
        old_active = user.active
        user.display_name = display_name
        user.email = email
        user.role = role
        user.active = active
        if old_role != role:
            audit(db, request, "admin_role_changed", "admin", user.id, f"{old_role}->{role}")
        if old_active and not active:
            audit(db, request, "admin_user_disabled", "admin", user.id)
        elif not old_active and active:
            audit(db, request, "admin_user_reactivated", "admin", user.id)
        audit(db, request, "admin_user_updated", "admin", user.id)
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/admin/users/{user_id}/reset-password", response_class=HTMLResponse)
def admin_user_reset_password_page(request: Request, user_id: int):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    with SessionLocal() as db:
        user = db.get(AdminUser, user_id)
        if user is None:
            return HTMLResponse("Not found", status_code=404)
        return render(request, "admin_user_reset_password.html", user=user, error=None)


@router.post("/admin/users/{user_id}/reset-password", response_class=HTMLResponse)
async def admin_user_reset_password(request: Request, user_id: int):
    gate = role_gate(request, {"super_admin"})
    if gate:
        return gate
    form = await request.form()
    password = str(form.get("password") or "")
    confirm_password = str(form.get("confirm_password") or "")
    error = _validate_password_pair(password, confirm_password)
    with SessionLocal() as db:
        user = db.get(AdminUser, user_id)
        if user is None:
            return HTMLResponse("Not found", status_code=404)
        if error:
            return render(request, "admin_user_reset_password.html", user=user, error=error)
        user.password_hash = hash_password(password)
        user.must_change_password = str(form.get("must_change_password") or "") == "1"
        audit(db, request, "admin_password_reset", "admin", user.id)
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    geo_backfilled = parse_int(request.query_params.get("geo_backfilled"))
    with SessionLocal() as db:
        stats = {
            "people": db.scalar(select(func.count(MissingPerson.id)).where(MissingPerson.archived.is_(False))) or 0,
            "published": db.scalar(
                select(func.count(MissingPerson.id)).where(
                    MissingPerson.published.is_(True), MissingPerson.archived.is_(False)
                )
            )
            or 0,
            "pending": db.scalar(select(func.count(Submission.id)).where(Submission.status == "pending")) or 0,
            "candidates": db.scalar(
                select(func.count(DiscoveryCandidate.id)).where(DiscoveryCandidate.status == "new")
            )
            or 0,
            "sources": db.scalar(select(func.count(Source.id))) or 0,
            "to_review": db.scalar(
                select(func.count(DiscoveryCandidate.id)).where(
                    DiscoveryCandidate.status.in_(["new", "needs_ai"])
                )
            ) or 0,
            "relevant": db.scalar(
                select(func.count(DiscoveryCandidate.id)).where(
                    DiscoveryCandidate.status == "relevant"
                )
            ) or 0,
            "duplicates": db.scalar(
                select(func.count(DiscoveryCandidate.id)).where(
                    DiscoveryCandidate.status == "possible_duplicate"
                )
            ) or 0,
            "unpublished": db.scalar(
                select(func.count(MissingPerson.id)).where(
                    MissingPerson.archived.is_(False),
                    MissingPerson.published.is_(False),
                )
            ) or 0,
        }
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all())
        active_disaster = next((d for d in disasters if d.active), disasters[0] if disasters else None)
        map_people = []
        if active_disaster is not None:
            map_people = [
                {
                    "case_number": p.case_number,
                    "name": p.name,
                    "lat": p.last_seen_lat,
                    "lon": p.last_seen_lon,
                    "location": p.last_seen_location,
                }
                for p in db.scalars(
                    select(MissingPerson).where(
                        MissingPerson.disaster_id == active_disaster.id,
                        MissingPerson.published.is_(True),
                        MissingPerson.archived.is_(False),
                        MissingPerson.last_seen_lat.is_not(None),
                        MissingPerson.last_seen_lon.is_not(None),
                    )
                ).all()
            ]
        return render(
            request,
            "admin_dashboard.html",
            stats=stats,
            disasters=disasters,
            active_disaster=active_disaster,
            map_people_json=json.dumps(map_people),
            geo_backfilled=geo_backfilled,
        )


@router.get("/admin/help", response_class=HTMLResponse)
def admin_help(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    return render(
        request,
        "admin_help.html",
        manual_deck_exists=MANUAL_DECK_PATH.exists(),
        manual_deck_url="/admin/help/manual.pptx" if MANUAL_DECK_PATH.exists() else None,
    )


@router.get("/admin/help/manual.pptx")
def admin_help_manual(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    if not MANUAL_DECK_PATH.exists():
        return HTMLResponse("Manual deck not found", status_code=404)
    return FileResponse(
        MANUAL_DECK_PATH,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="user_manual_bilingual.pptx",
    )


@router.get("/admin/events", response_class=HTMLResponse)
def admin_events(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all())
        return render(request, "admin_events.html", disasters=disasters, error=None)


@router.post("/admin/events")
async def admin_event_create(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    code = str(form.get("code") or "").strip().upper()
    name = str(form.get("name") or "").strip()
    start_date = parse_date(form.get("start_date"))
    if not code or not name or not start_date:
        return RedirectResponse("/admin/events", status_code=303)
    with SessionLocal() as db:
        affected_locations = str(form.get("affected_locations") or "").strip()
        center = _geo_point_for_text(affected_locations.splitlines()[0].strip()) if affected_locations else None
        disaster = Disaster(
            code=code,
            name=name,
            disaster_type=str(form.get("disaster_type") or "flood").strip(),
            start_date=start_date,
            affected_locations=affected_locations,
            center_lat=center.lat if center else None,
            center_lon=center.lon if center else None,
            boundary_geojson=str(form.get("boundary_geojson") or "").strip() or None,
            active=True,
        )
        db.add(disaster)
        try:
            db.flush()
            audit(db, request, "create_event", "disaster", disaster.id, name)
            db.commit()
        except IntegrityError:
            db.rollback()
    return RedirectResponse("/admin/events", status_code=303)


@router.post("/admin/events/{disaster_id}/update")
async def admin_event_update(request: Request, disaster_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    with SessionLocal() as db:
        disaster = db.get(Disaster, disaster_id)
        if disaster is None:
            return HTMLResponse("Not found", status_code=404)
        affected_locations = str(form.get("affected_locations") or "").strip()
        center = _geo_point_for_text(affected_locations.splitlines()[0].strip()) if affected_locations else None
        disaster.name = str(form.get("name") or disaster.name).strip()
        disaster.disaster_type = str(form.get("disaster_type") or disaster.disaster_type).strip()
        disaster.affected_locations = affected_locations
        disaster.center_lat = center.lat if center else None
        disaster.center_lon = center.lon if center else None
        disaster.boundary_geojson = str(form.get("boundary_geojson") or "").strip() or None
        disaster.active = str(form.get("active") or "") == "on"
        audit(db, request, "update_event", "disaster", disaster.id, disaster.name)
        db.commit()
    return RedirectResponse("/admin/events", status_code=303)


@router.get("/admin/people", response_class=HTMLResponse)
def admin_people(
    request: Request,
    disaster_id: int | None = None,
    q: str = "",
    case_status: str = "missing",
):
    gate = admin_gate(request)
    if gate:
        return gate
    case_status = case_status.strip().casefold()
    if case_status not in {"missing", "found", "identified", "all"}:
        case_status = "missing"

    with SessionLocal() as db:
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all())
        stmt = (
            select(MissingPerson)
            .options(selectinload(MissingPerson.sources))
            .outerjoin(PersonCaseState, PersonCaseState.person_id == MissingPerson.id)
            .where(MissingPerson.archived.is_(False))
            .order_by(MissingPerson.created_at.desc())
        )
        if disaster_id:
            stmt = stmt.where(MissingPerson.disaster_id == disaster_id)
        if case_status != "all":
            stmt = stmt.where(
                func.coalesce(PersonCaseState.status, "missing") == case_status
            )
        if q.strip():
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    MissingPerson.name.ilike(pattern),
                    MissingPerson.name_ne.ilike(pattern),
                    MissingPerson.case_number.ilike(pattern),
                )
            )
        people = list(db.scalars(stmt.limit(500)).all())
        status_map = _person_case_status_map(db, [person.id for person in people])

        counts: dict[str, int] = {}
        for status_name in ("missing", "found", "identified"):
            count_stmt = (
                select(func.count(MissingPerson.id))
                .select_from(MissingPerson)
                .outerjoin(PersonCaseState, PersonCaseState.person_id == MissingPerson.id)
                .where(
                    MissingPerson.archived.is_(False),
                    func.coalesce(PersonCaseState.status, "missing") == status_name,
                )
            )
            if disaster_id:
                count_stmt = count_stmt.where(MissingPerson.disaster_id == disaster_id)
            counts[status_name] = db.scalar(count_stmt) or 0
        counts["all"] = sum(counts.values())

        return render(
            request,
            "admin_people.html",
            people=people,
            disasters=disasters,
            selected_disaster=disaster_id,
            q=q,
            case_status=case_status,
            status_map=status_map,
            status_counts=counts,
        )


@router.get("/admin/people/{person_id}", response_class=HTMLResponse)
def admin_person(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        person = db.scalar(
            select(MissingPerson)
            .options(selectinload(MissingPerson.sources))
            .where(MissingPerson.id == person_id)
        )
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        merge_targets = list(
            db.scalars(
                select(MissingPerson).where(
                    MissingPerson.disaster_id == person.disaster_id,
                    MissingPerson.id != person.id,
                    MissingPerson.archived.is_(False),
                ).order_by(MissingPerson.name)
            ).all()
        )
        return render(
            request,
            "admin_person.html",
            person=person,
            error=None,
            public_url=f"{settings.public_base_url}/person/{person.case_number}",
            merge_targets=merge_targets,
            case_status=_person_case_status_map(db, [person.id]).get(person.id, "missing"),
            subscriptions=list(db.scalars(select(NotificationSubscription).where(NotificationSubscription.person_id == person.id)).all()),
            notification_counts={
                status: db.scalar(
                    select(func.count(NotificationOutbox.id)).where(
                        NotificationOutbox.person_id == person.id,
                        NotificationOutbox.status == status,
                    )
                ) or 0
                for status in ("pending", "sent", "failed")
            },
            mask_destination=mask_destination,
            timeline=list(db.scalars(
                select(CaseTimeline)
                .where(CaseTimeline.person_id == person.id)
                .order_by(CaseTimeline.created_at.desc())
            ).all()),
        )


@router.post("/admin/people/{person_id}/edit")
async def admin_person_edit(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        person.name = str(form.get("name") or person.name).strip()
        person.name_ne = str(form.get("name_ne") or "").strip() or None
        person.age = parse_int(form.get("age"))
        person.gender = _normalize_gender(form.get("gender"))
        person.last_seen_date = parse_date(form.get("last_seen_date"))
        person.last_seen_time = parse_time(form.get("last_seen_time"))
        last_seen_location = str(form.get("last_seen_location") or "").strip()
        person.last_seen_location = last_seen_location
        point = _geo_point_for_text(last_seen_location) if last_seen_location else None
        person.last_seen_lat = point.lat if point else None
        person.last_seen_lon = point.lon if point else None
        person.clothing = str(form.get("clothing") or "").strip() or None
        person.identification_details = str(form.get("identification_details") or "").strip() or None
        person.public_contact_number = str(form.get("public_contact_number") or "").strip() or None
        person.source_confirmed = str(form.get("source_confirmed") or "") == "1"
        person.verification_confidence = str(form.get("verification_confidence") or "").strip().casefold() or None
        person.verified_by = str(request.session.get("admin") or "system")
        person.verified_at = utcnow()
        person.approval_notes = str(form.get("approval_notes") or "").strip() or None
        person.location_uncertain = str(form.get("location_uncertain") or "") == "1"
        person.residential_address_private = str(form.get("residential_address_private") or "").strip() or None
        photo_upload = form.get("photo")
        if photo_upload is not None and getattr(photo_upload, "filename", ""):
            try:
                photo_path = await save_image(photo_upload, settings.upload_dir)
            except ValueError as exc:
                return HTMLResponse(str(exc), status_code=400)
            if photo_path:
                person.photo_path = photo_path
        if str(form.get("meaningful_update") or "") == "1":
            enqueue_case_notifications(
                db,
                person,
                CASE_UPDATED,
                update_note=str(form.get("status_note") or "").strip() or None,
            )
        audit(db, request, "edit_person", "person", person.id)
        _add_case_timeline(db, request, person.id, "case_edited", "Case details updated")
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/photo/remove")
def admin_person_remove_photo(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    filename = None
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        filename = person.photo_path
        if filename:
            person.photo_path = None
            audit(
                db,
                request,
                "remove_person_photo",
                "person",
                person.id,
                "replaced with default placeholder",
            )
            db.commit()

            still_referenced = db.scalar(
                select(func.count()).select_from(Submission).where(
                    Submission.photo_path == filename
                )
            ) or db.scalar(
                select(func.count()).select_from(MissingPerson).where(
                    MissingPerson.photo_path == filename
                )
            )
            if not still_referenced and Path(filename).name == filename:
                try:
                    (settings.upload_dir / filename).unlink(missing_ok=True)
                except OSError:
                    # The database change is authoritative; orphan cleanup can retry later.
                    pass
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/notifications")
async def admin_person_add_notification(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    with SessionLocal() as db:
        if db.get(MissingPerson, person_id) is None:
            return HTMLResponse("Not found", status_code=404)
        try:
            subscription = add_subscription(
                db,
                person_id,
                str(form.get("channel") or ""),
                str(form.get("destination") or ""),
            )
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=400)
        audit(
            db,
            request,
            "add_notification_subscription",
            "notification_subscription",
            subscription.id,
            subscription.channel,
        )
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/notifications/{subscription_id}/disable")
def admin_person_disable_notification(request: Request, person_id: int, subscription_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        subscription = db.get(NotificationSubscription, subscription_id)
        if subscription and subscription.person_id == person_id:
            subscription.active = False
            audit(db, request, "disable_notification_subscription", "notification_subscription", subscription.id)
            db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/notifications/retry")
def admin_person_retry_notifications(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        retry_failed_notifications(db, person_id)
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/notifications/cancel")
def admin_person_cancel_notifications(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        cancel_pending_notifications(db, person_id)
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/status")
async def admin_person_status(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    status = str(form.get("case_status") or "").strip().casefold()
    note = str(form.get("status_note") or "").strip()
    if status not in PERSON_CASE_STATUSES:
        return HTMLResponse("Invalid case status", status_code=400)

    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        previous_status = _person_case_status_map(db, [person.id]).get(person.id, "missing")
        _set_person_case_status(db, person, status, note)
        if previous_status == "missing" and status == "found":
            enqueue_case_notifications(db, person, FOUND_ALIVE)
        elif previous_status == "missing" and status == "identified":
            enqueue_case_notifications(db, person, IDENTIFIED_DECEASED)
        audit(
            db,
            request,
            "update_person_case_status",
            "person",
            person.id,
            f"status={status}; note={note[:300]}",
        )
        _add_case_timeline(db, request, person.id, f"status_{status}", note)
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/publish")
def admin_publish(request: Request, person_id: int):
    gate = role_gate(request, {"super_admin", "admin"})
    if gate:
        return gate
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person:
            person.published = not person.published
            audit(db, request, "publish_toggle", "person", person.id, str(person.published))
            _add_case_timeline(db, request, person.id, "published" if person.published else "unpublished")
            db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/archive")
def admin_archive(request: Request, person_id: int):
    gate = role_gate(request, {"super_admin", "admin"})
    if gate:
        return gate
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person:
            person.archived = True
            person.published = False
            audit(db, request, "archive_person", "person", person.id)
            _add_case_timeline(db, request, person.id, "archived")
            db.commit()
    return RedirectResponse("/admin/people", status_code=303)


@router.post("/admin/people/{person_id}/merge")
async def admin_merge_person(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    target_id = parse_int(form.get("target_person_id"))
    if not target_id or target_id == person_id:
        return RedirectResponse(f"/admin/people/{person_id}", status_code=303)
    with SessionLocal() as db:
        source = db.scalar(
            select(MissingPerson).options(selectinload(MissingPerson.sources)).where(MissingPerson.id == person_id)
        )
        target = db.scalar(
            select(MissingPerson).options(selectinload(MissingPerson.sources)).where(MissingPerson.id == target_id)
        )
        if source is None or target is None or source.disaster_id != target.disaster_id:
            return HTMLResponse("Invalid merge target", status_code=400)

        target_urls = {item.url for item in target.sources}
        for source_item in list(source.sources):
            if source_item.url in target_urls:
                db.delete(source_item)
            else:
                source_item.person_id = target.id
                target_urls.add(source_item.url)

        db.execute(
            Submission.__table__.update()
            .where(Submission.person_id == source.id)
            .values(person_id=target.id)
        )

        # Fill only blank canonical fields. The target remains the admin-selected master record.
        for field in [
            "name_ne", "age", "gender", "photo_path", "residential_address_private",
            "last_seen_date", "last_seen_time", "clothing", "identification_details",
            "public_contact_number", "private_contact_number",
        ]:
            if getattr(target, field) in (None, "") and getattr(source, field) not in (None, ""):
                setattr(target, field, getattr(source, field))
        if not target.last_seen_location and source.last_seen_location:
            target.last_seen_location = source.last_seen_location

        source.archived = True
        source.published = False
        audit(
            db,
            request,
            "merge_duplicate_person",
            "person",
            source.id,
            f"merged_into={target.id}; target_case={target.case_number}",
        )
        db.commit()
    return RedirectResponse(f"/admin/people/{target_id}", status_code=303)


@router.post("/admin/people/{person_id}/source")
async def admin_add_source(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    url = canonicalize_url(str(form.get("url") or ""))
    if not url:
        return RedirectResponse(f"/admin/people/{person_id}", status_code=303)
    with SessionLocal() as db:
        if db.get(MissingPerson, person_id) is None:
            return HTMLResponse("Not found", status_code=404)
        existing = db.scalar(select(Source).where(Source.person_id == person_id, Source.url == url))
        if existing is None:
            source = Source(
                person_id=person_id,
                platform=str(form.get("platform") or "facebook").strip(),
                url=url,
                source_name=str(form.get("source_name") or "").strip() or None,
                source_text=str(form.get("source_text") or "").strip() or None,
            )
            db.add(source)
            db.flush()
            audit(db, request, "add_source", "source", source.id, url)
            db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.get("/admin/submissions", response_class=HTMLResponse)
def admin_submissions(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        submissions = list(
            db.scalars(
                select(Submission).where(Submission.status == "pending").order_by(Submission.created_at.desc())
            ).all()
        )
        duplicate_map: dict[int, list[tuple[MissingPerson, float]]] = {}
        location_match_map: dict[int, bool] = {}
        disasters_by_id = {d.id: d for d in db.scalars(select(Disaster)).all()}
        for sub in submissions:
            disaster = disasters_by_id.get(sub.disaster_id)
            location_match_map[sub.id] = bool(
                disaster and affected_location_match(sub.last_seen_location, disaster.affected_locations)
            )
            if sub.kind == "missing_report" and sub.name:
                duplicate_map[sub.id] = find_duplicates(
                    db,
                    disaster_id=sub.disaster_id,
                    name=sub.name,
                    location=sub.last_seen_location,
                    age=sub.age,
                    phone=sub.public_contact_number,
                )
        people = list(
            db.scalars(
                select(MissingPerson).where(MissingPerson.archived.is_(False)).order_by(MissingPerson.name)
            ).all()
        )
        people_by_disaster: dict[int, list[MissingPerson]] = {}
        for person in people:
            people_by_disaster.setdefault(person.disaster_id, []).append(person)
        return render(
            request,
            "admin_submissions.html",
            submissions=submissions,
            duplicate_map=duplicate_map,
            location_match_map=location_match_map,
            people_by_disaster=people_by_disaster,
        )


@router.post("/admin/submissions/{submission_id}/acknowledge")
def acknowledge_panic_alert(request: Request, submission_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        if submission is None or submission.kind != "panic_alert":
            return HTMLResponse("SOS alert not found", status_code=404)
        submission.status = "reviewed"
        audit(db, request, "acknowledge_panic_alert", "submission", submission.id)
        db.commit()
    return RedirectResponse("/admin/submissions", status_code=303)


@router.post("/admin/submissions/{submission_id}/approve-new")
async def approve_submission_new(request: Request, submission_id: int):
    gate = role_gate(request, {"super_admin", "admin"})
    if gate:
        return gate
    form = await request.form()
    publish_now = str(form.get("publish") or "") == "1"
    with SessionLocal() as db:
        sub = db.get(Submission, submission_id)
        if sub is None or sub.status != "pending" or not sub.name:
            return RedirectResponse("/admin/submissions", status_code=303)
        disaster = db.get(Disaster, sub.disaster_id)
        if disaster is None:
            return RedirectResponse("/admin/submissions", status_code=303)
        person = MissingPerson(
            case_number=next_case_number(db, disaster),
            disaster_id=sub.disaster_id,
            name=sub.name,
            name_ne=sub.name_ne,
            age=sub.age,
            gender=sub.gender,
            photo_path=sub.photo_path,
            residential_address_private=sub.residential_address_private,
            last_seen_date=sub.last_seen_date,
            last_seen_time=sub.last_seen_time,
            last_seen_location=sub.last_seen_location or "Unknown",
            clothing=sub.clothing,
            identification_details=sub.identification_details,
            public_contact_number=sub.public_contact_number,
            private_contact_number=sub.reporter_phone_private,
            source_confirmed=sub.source_confirmed,
            verification_confidence=sub.verification_confidence,
            verified_by=str(request.session.get("admin") or "system"),
            verified_at=utcnow(),
            approval_notes=sub.approval_notes,
            location_uncertain=sub.location_uncertain,
            published=publish_now,
        )
        db.add(person)
        db.flush()
        db.add(PersonCaseState(person_id=person.id, status="missing"))
        sub.person_id = person.id
        sub.status = "approved"
        _add_case_timeline(db, request, person.id, "created_from_submission", f"Submission {sub.id} approved")
        if publish_now:
            _add_case_timeline(db, request, person.id, "published", "Published during submission approval")
        if sub.social_url:
            db.add(
                Source(
                    person_id=person.id,
                    platform=detect_platform(sub.social_url),
                    url=sub.social_url,
                    source_text=sub.notes,
                )
            )
        audit(
            db,
            request,
            "approve_submission_new",
            "person",
            person.id,
            f"submission={sub.id}; published={publish_now}",
        )
        db.commit()
        return RedirectResponse(f"/admin/people/{person.id}", status_code=303)


@router.post("/admin/submissions/{submission_id}/attach")
async def attach_submission(request: Request, submission_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    person_id = parse_int(form.get("person_id"))
    with SessionLocal() as db:
        sub = db.get(Submission, submission_id)
        person = db.get(MissingPerson, person_id) if person_id else None
        if sub is None or person is None:
            return RedirectResponse("/admin/submissions", status_code=303)
        if person.disaster_id != sub.disaster_id:
            return HTMLResponse("Cannot attach a submission to a person from a different disaster", status_code=400)
        if sub.status != "pending":
            return RedirectResponse("/admin/submissions", status_code=303)

        updated_fields = apply_submission_to_master(
            person,
            sub,
        )

        if sub.social_url:
            existing = db.scalar(select(Source).where(Source.person_id == person.id, Source.url == sub.social_url))
            if existing is None:
                db.add(
                    Source(
                        person_id=person.id,
                        platform=detect_platform(sub.social_url),
                        url=sub.social_url,
                        source_text=sub.notes,
                    )
                )
        sub.person_id = person.id
        sub.status = "attached"
        audit(
            db,
            request,
            "attach_submission",
            "person",
            person.id,
            (
                f"submission={sub.id}; "
                f"master_fields_updated={','.join(updated_fields) or 'none'}"
            ),
        )
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)



@router.post(
    "/admin/submissions/{submission_id}/edit"
)
async def edit_pending_submission(
    request: Request,
    submission_id: int,
):
    gate = admin_gate(request)

    if gate:
        return gate

    form = await request.form()

    with SessionLocal() as db:
        sub = db.get(
            Submission,
            submission_id,
        )

        if (
            sub is None
            or sub.status != "pending"
        ):
            return RedirectResponse(
                "/admin/submissions",
                status_code=303,
            )

        name = str(
            form.get("name")
            or ""
        ).strip()

        if (
            sub.kind == "missing_report"
            and not name
        ):
            return HTMLResponse(
                "Name is required",
                status_code=400,
            )

        sub.name = name or sub.name

        sub.name_ne = (
            str(
                form.get("name_ne")
                or ""
            ).strip()
            or None
        )

        sub.age = parse_int(
            form.get("age")
        )

        sub.gender = _normalize_gender(form.get("gender"))

        sub.last_seen_date = parse_date(
            form.get("last_seen_date")
        )

        sub.last_seen_time = parse_time(
            form.get("last_seen_time")
        )

        sub.last_seen_location = (
            str(
                form.get(
                    "last_seen_location"
                )
                or ""
            ).strip()
            or None
        )

        sub.clothing = (
            str(
                form.get("clothing")
                or ""
            ).strip()
            or None
        )

        sub.identification_details = (
            str(
                form.get(
                    "identification_details"
                )
                or ""
            ).strip()
            or None
        )

        sub.public_contact_number = (
            str(
                form.get(
                    "public_contact_number"
                )
                or ""
            ).strip()
            or None
        )

        photo_upload = form.get(
            "photo"
        )

        if (
            photo_upload is not None
            and getattr(
                photo_upload,
                "filename",
                "",
            )
        ):
            try:
                photo_path = await save_image(
                    photo_upload,
                    settings.upload_dir,
                )
            except ValueError as exc:
                return HTMLResponse(
                    str(exc),
                    status_code=400,
                )

            if photo_path:
                sub.photo_path = photo_path

        audit(
            db,
            request,
            "edit_pending_submission",
            "submission",
            sub.id,
            "admin-reviewed extracted details",
        )

        db.commit()

    return RedirectResponse(
        "/admin/submissions",
        status_code=303,
    )


@router.post("/admin/submissions/{submission_id}/reject")
def reject_submission(request: Request, submission_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        sub = db.get(Submission, submission_id)
        if sub:
            sub.status = "rejected"
            audit(db, request, "reject_submission", "submission", sub.id)
            db.commit()
    return RedirectResponse("/admin/submissions", status_code=303)


@router.get("/admin/discovery", response_class=HTMLResponse)
def discovery_page(
    request: Request,
    disaster_id: int | None = None,
    platform: str = "facebook",
    view: str = "review",
    q: str = "",
    wide_queries: int | None = None,
    wide_raw: int | None = None,
    wide_added: int | None = None,
    wide_error: int | None = None,
    queue_complete: int | None = None,
    batch_prefilled: int | None = None,
    batch_skipped: int | None = None,
    batch_failed: int | None = None,
):
    gate = admin_gate(request)
    if gate:
        return gate

    allowed_views = {"review", "relevant", "duplicates", "irrelevant", "processed"}
    view = view.casefold().strip()
    if view not in allowed_views:
        view = "review"

    with SessionLocal() as db:
        disasters = list(
            db.scalars(
                select(Disaster).order_by(
                    Disaster.active.desc(),
                    Disaster.start_date.desc(),
                )
            ).all()
        )
        selected = (
            db.get(Disaster, disaster_id)
            if disaster_id
            else next((d for d in disasters if d.active), disasters[0] if disasters else None)
        )

        queries = (
            generate_queries(selected, platform=platform)
            if selected
            else []
        )

        wide_provider_status = serper_status()
        wide_query_plan: list[str] = []
        published_urls: set[str] = set()
        queue_counts = {
            "review": 0,
            "relevant": 0,
            "duplicates": 0,
            "irrelevant": 0,
            "processed": 0,
        }
        candidates: list[DiscoveryCandidate] = []
        pipeline_counts = {"pending": 0, "unpublished": 0, "published": 0}

        if selected:
            pipeline_counts["pending"] = db.scalar(
                select(func.count(Submission.id)).where(
                    Submission.disaster_id == selected.id,
                    Submission.status == "pending",
                    Submission.kind == "missing_report",
                )
            ) or 0
            pipeline_counts["unpublished"] = db.scalar(
                select(func.count(MissingPerson.id)).where(
                    MissingPerson.disaster_id == selected.id,
                    MissingPerson.archived.is_(False),
                    MissingPerson.published.is_(False),
                )
            ) or 0
            pipeline_counts["published"] = db.scalar(
                select(func.count(MissingPerson.id))
                .outerjoin(PersonCaseState, PersonCaseState.person_id == MissingPerson.id)
                .where(
                    MissingPerson.disaster_id == selected.id,
                    MissingPerson.archived.is_(False),
                    MissingPerson.published.is_(True),
                    func.coalesce(PersonCaseState.status, "missing") == "missing",
                )
            ) or 0
            if platform == "facebook":
                scopes = collect_known_source_scopes(db, selected.id)
                custom_tag_rows = user_search_tags(db, selected.id, platform)
                manual_source_rows = user_source_seeds(db, selected.id, platform)
                wide_query_plan = generate_wide_queries(
                    selected,
                    source_scopes=scopes,
                    custom_tags=[row.tag for row in custom_tag_rows],
                    manual_source_scopes=[row.scope for row in manual_source_rows],
                    manual_sources=[(row.label, row.scope) for row in manual_source_rows],
                )

            published_urls = set(
                db.scalars(
                    select(Source.url)
                    .join(MissingPerson, Source.person_id == MissingPerson.id)
                    .where(
                        MissingPerson.disaster_id == selected.id,
                        MissingPerson.published.is_(True),
                        MissingPerson.archived.is_(False),
                    )
                ).all()
            )

            base_conditions = [
                DiscoveryCandidate.disaster_id == selected.id,
                DiscoveryCandidate.platform == platform,
            ]

            status_groups = {
                "review": ["new", "needs_ai"],
                "relevant": ["relevant"],
                "duplicates": ["possible_duplicate"],
                "irrelevant": ["irrelevant", "rejected"],
                "processed": ["reviewed"],
            }

            for key, statuses in status_groups.items():
                count_stmt = (
                    select(func.count(DiscoveryCandidate.id))
                    .where(*base_conditions)
                    .where(DiscoveryCandidate.status.in_(statuses))
                )
                if key in {"review", "relevant"} and published_urls:
                    count_stmt = count_stmt.where(
                        DiscoveryCandidate.url.notin_(published_urls)
                    )
                queue_counts[key] = db.scalar(count_stmt) or 0

            stmt = (
                select(DiscoveryCandidate)
                .where(*base_conditions)
                .where(DiscoveryCandidate.status.in_(status_groups[view]))
                .order_by(DiscoveryCandidate.found_at.desc())
            )

            if view in {"review", "relevant"} and published_urls:
                stmt = stmt.where(
                    DiscoveryCandidate.url.notin_(published_urls)
                )

            if q.strip():
                pattern = f"%{q.strip()}%"
                stmt = stmt.where(
                    or_(
                        DiscoveryCandidate.title.ilike(pattern),
                        DiscoveryCandidate.snippet.ilike(pattern),
                    )
                )

            candidates = list(db.scalars(stmt.limit(300)).all())

        base_params = {
            "disaster_id": selected.id if selected else "",
            "platform": platform,
        }
        queue_links = {
            key: "/admin/discovery?" + urlencode(
                {**base_params, "view": key, **({"q": q.strip()} if q.strip() else {})}
            )
            for key in allowed_views
        }
        clear_search_url = "/admin/discovery?" + urlencode(
            {**base_params, "view": view}
        )

        priority_searches = []
        custom_tags = []
        custom_tag_searches = []
        manual_sources = []
        auto_sources = []
        if selected and platform == "facebook":
            priority_searches = [
                {
                    **item,
                    "url": google_search_url(item["query"], selected.start_date),
                    "secondary_url": google_search_url(item["secondary_query"], selected.start_date),
                }
                for item in priority_manual_searches(selected)
            ]
            custom_tags = user_search_tags(db, selected.id, platform)
            for tag_row in custom_tags:
                custom_tag_searches.append(
                    {
                        "row": tag_row,
                        "queries": [
                            (query, google_search_url(query, selected.start_date))
                            for query in custom_tag_queries(selected, [tag_row.tag])
                        ],
                    }
                )
            manual_sources = user_source_seeds(db, selected.id, platform)
            auto_sources = discovered_source_activity(db, selected.id)
            already_scoped = {scope.casefold() for scope in priority_source_scopes()} | {
                row.scope.casefold() for row in manual_sources
            }
            auto_sources = [
                item for item in auto_sources
                if str(item["scope"]).casefold() not in already_scoped
            ]

        return render(
            request,
            "admin_discovery.html",
            disasters=disasters,
            selected=selected,
            platform=platform,
            view=view,
            q=q,
            queue_counts=queue_counts,
            queue_links=queue_links,
            clear_search_url=clear_search_url,
            queries=[(item, google_search_url(item, selected.start_date)) for item in queries] if selected else [],
            priority_searches=priority_searches,
            custom_tags=custom_tags,
            custom_tag_searches=custom_tag_searches,
            manual_sources=manual_sources,
            auto_sources=auto_sources,
            candidates=candidates,
            bot_message=None,
            wide_stats=(
                {"queries": wide_queries, "raw": wide_raw, "added": wide_added}
                if wide_queries is not None
                else None
            ),
            wide_provider_status=wide_provider_status,
            wide_query_plan=wide_query_plan,
            wide_error=bool(wide_error),
            queue_complete=bool(queue_complete),
            batch_prefilled=batch_prefilled,
            batch_skipped=batch_skipped,
            batch_failed=batch_failed,
            pipeline_counts=pipeline_counts,
        )


@router.post("/admin/discovery/run")
async def discovery_run(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    platform = str(form.get("platform") or "facebook")
    with SessionLocal() as db:
        disaster = db.get(Disaster, disaster_id) if disaster_id else None
        if disaster is None:
            return RedirectResponse("/admin/discovery", status_code=303)
        added = discover_candidates(db, disaster, platform=platform)
        audit(db, request, "run_discovery_bot", "disaster", disaster.id, f"platform={platform}; added={added}")
        db.commit()
    return RedirectResponse(f"/admin/discovery?disaster_id={disaster_id}&platform={platform}", status_code=303)



@router.post("/admin/wide-discovery/run")
async def wide_discovery_run(
    request: Request,
):
    gate = admin_gate(request)

    if gate:
        return gate

    form = await request.form()

    disaster_id = parse_int(
        form.get("disaster_id")
    )

    with SessionLocal() as db:
        disaster = (
            db.get(
                Disaster,
                disaster_id,
            )
            if disaster_id
            else None
        )

        if disaster is None:
            return RedirectResponse(
                "/admin/discovery",
                status_code=303,
            )

        try:
            stats = run_wide_discovery(
                db,
                disaster,
            )
        except SearchProviderUnavailable:
            return RedirectResponse(
                (
                    "/admin/discovery"
                    f"?disaster_id={disaster_id}"
                    "&platform=facebook"
                    "&wide_error=1"
                ),
                status_code=303,
            )

        audit(
            db,
            request,
            "run_wide_discovery",
            "disaster",
            disaster.id,
            (
                f"queries={stats['queries']}; "
                f"raw={stats['raw_results']}; "
                f"needs_ai={stats['needs_ai']}"
            ),
        )

        db.commit()

    return RedirectResponse(
        (
            "/admin/discovery"
            f"?disaster_id={disaster_id}"
            "&platform=facebook"
            f"&wide_queries={stats['queries']}"
            f"&wide_raw={stats['raw_results']}"
            f"&wide_added={stats['needs_ai']}"
        ),
        status_code=303,
    )


@router.post("/admin/discovery/search-tags")
async def discovery_add_search_tag(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    platform = str(form.get("platform") or "facebook").strip().casefold()
    tag = " ".join(str(form.get("tag") or "").split())
    if not disaster_id or not tag:
        return RedirectResponse("/admin/discovery", status_code=303)
    if len(tag) > 255:
        return HTMLResponse("Search tag is too long", status_code=400)

    with SessionLocal() as db:
        existing = db.scalar(
            select(DiscoverySearchTag).where(
                DiscoverySearchTag.disaster_id == disaster_id,
                DiscoverySearchTag.platform == platform,
                func.lower(DiscoverySearchTag.tag) == tag.casefold(),
            )
        )
        if existing is None:
            row = DiscoverySearchTag(
                disaster_id=disaster_id,
                platform=platform,
                tag=tag,
                active=True,
            )
            db.add(row)
            db.flush()
            audit(db, request, "add_discovery_search_tag", "discovery_search_tag", row.id, tag)
        else:
            existing.active = True
        db.commit()
    return RedirectResponse(
        f"/admin/discovery?disaster_id={disaster_id}&platform={platform}#custom-search-tags",
        status_code=303,
    )


@router.post("/admin/discovery/search-tags/{tag_id}/delete")
async def discovery_delete_search_tag(request: Request, tag_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    platform = str(form.get("platform") or "facebook").strip().casefold()
    with SessionLocal() as db:
        row = db.get(DiscoverySearchTag, tag_id)
        if row is not None:
            row.active = False
            audit(db, request, "disable_discovery_search_tag", "discovery_search_tag", row.id, row.tag)
            disaster_id = row.disaster_id
            platform = row.platform
            db.commit()
    return RedirectResponse(
        f"/admin/discovery?disaster_id={disaster_id or ''}&platform={platform}#custom-search-tags",
        status_code=303,
    )


@router.post("/admin/discovery/source-seeds")
async def discovery_add_source_seed(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    platform = str(form.get("platform") or "facebook").strip().casefold()
    label = " ".join(str(form.get("label") or "").split())
    source_value = str(form.get("source") or "").strip()
    scope = normalize_facebook_source_scope(source_value)
    if not disaster_id or platform != "facebook" or not scope:
        return HTMLResponse(
            "Enter a valid public Facebook page/group URL or page/group scope.",
            status_code=400,
        )
    label = label or scope
    if len(label) > 255 or len(scope) > 255:
        return HTMLResponse("Source name is too long", status_code=400)

    with SessionLocal() as db:
        existing = db.scalar(
            select(DiscoverySourceSeed).where(
                DiscoverySourceSeed.disaster_id == disaster_id,
                DiscoverySourceSeed.platform == platform,
                func.lower(DiscoverySourceSeed.scope) == scope.casefold(),
            )
        )
        if existing is None:
            row = DiscoverySourceSeed(
                disaster_id=disaster_id,
                platform=platform,
                label=label,
                scope=scope,
                source_url=source_url_for_scope(scope),
                active=True,
            )
            db.add(row)
            db.flush()
            audit(db, request, "add_discovery_source_seed", "discovery_source_seed", row.id, scope)
        else:
            existing.active = True
            existing.label = label
            existing.source_url = source_url_for_scope(scope)
        db.commit()
    return RedirectResponse(
        f"/admin/discovery?disaster_id={disaster_id}&platform={platform}#source-finder",
        status_code=303,
    )


@router.post("/admin/discovery/source-seeds/{source_id}/delete")
async def discovery_delete_source_seed(request: Request, source_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    platform = str(form.get("platform") or "facebook").strip().casefold()
    with SessionLocal() as db:
        row = db.get(DiscoverySourceSeed, source_id)
        if row is not None:
            row.active = False
            audit(db, request, "disable_discovery_source_seed", "discovery_source_seed", row.id, row.scope)
            disaster_id = row.disaster_id
            platform = row.platform
            db.commit()
    return RedirectResponse(
        f"/admin/discovery?disaster_id={disaster_id or ''}&platform={platform}#source-finder",
        status_code=303,
    )


@router.post("/admin/discovery/manual")
async def discovery_manual(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate

    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    url = canonicalize_url(str(form.get("url") or ""))
    platform = str(form.get("platform") or "facebook").strip()
    title = str(form.get("title") or "").strip()
    manual_text = str(form.get("snippet") or "").strip()
    search_query = str(form.get("search_query") or "").strip()

    if not disaster_id or not url:
        return RedirectResponse("/admin/discovery", status_code=303)

    with SessionLocal() as db:
        existing = db.scalar(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.disaster_id == disaster_id,
                DiscoveryCandidate.url == url,
            )
        )

        if existing is None:
            query_value = (
                f"manual:{search_query}"
                if search_query
                else "manual-url"
            )
            candidate = DiscoveryCandidate(
                disaster_id=disaster_id,
                platform=platform,
                query=query_value,
                url=url,
                title=title or None,
                snippet=manual_text or None,
            )
            db.add(candidate)
            db.flush()
            audit(
                db,
                request,
                "add_manual_candidate",
                "discovery_candidate",
                candidate.id,
                (
                    f"url={url}; "
                    f"search_context={search_query or 'direct'}"
                ),
            )
        else:
            candidate = existing
            changes: list[str] = []

            # Human-entered context can enrich an existing automated result
            # without destroying the original indexed evidence.
            if title and not (candidate.title or "").strip():
                candidate.title = title
                changes.append("title")

            if manual_text:
                current = (candidate.snippet or "").strip()
                if manual_text not in current:
                    candidate.snippet = (
                        f"{current}\\n\\n[Manual context]\\n{manual_text}"
                        if current
                        else manual_text
                    )
                    changes.append("context")

            audit(
                db,
                request,
                "update_manual_candidate_context",
                "discovery_candidate",
                candidate.id,
                (
                    f"url={url}; "
                    f"search_context={search_query or 'direct'}; "
                    f"changes={','.join(changes) or 'none'}"
                ),
            )

        db.commit()
        candidate_id = candidate.id

    return RedirectResponse(
        f"/admin/discovery/{candidate_id}",
        status_code=303,
    )


@router.post("/admin/discovery/{candidate_id}/status")
async def discovery_candidate_status(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate

    form = await request.form()
    action = str(form.get("status_action") or "").strip().casefold()
    current_view = str(form.get("view") or "review").strip().casefold()
    platform = str(form.get("platform") or "facebook").strip()
    q = str(form.get("q") or "").strip()

    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)

        if action in {"relevant", "prefill"}:
            detected_names = extract_candidate_people_names(candidate)
            has_published_exact_match = any(
                _exact_published_name_matches(db, candidate.disaster_id, detected_name)
                for detected_name in detected_names
            )
            candidate.status = "possible_duplicate" if has_published_exact_match else "relevant"
        elif action == "irrelevant":
            candidate.status = "irrelevant"
        elif action == "restore":
            candidate.status = "needs_ai"
        elif action == "processed":
            candidate.status = "reviewed"
        elif action == "reopen":
            candidate.status = "relevant"
        elif action == "duplicate":
            candidate.status = "possible_duplicate"
        else:
            return HTMLResponse("Invalid discovery status", status_code=400)

        audit(
            db,
            request,
            "classify_discovery_candidate",
            "discovery_candidate",
            candidate.id,
            f"status={candidate.status}",
        )
        db.commit()

        params = {
            "disaster_id": candidate.disaster_id,
            "platform": platform,
            "view": current_view if current_view in {"review", "relevant", "duplicates", "irrelevant", "processed"} else "review",
        }
        if q:
            params["q"] = q

    if action == "prefill" and candidate.status == "relevant":
        return RedirectResponse(
            f"/admin/discovery/{candidate_id}?auto_prefill=1#chatgpt-prefill",
            status_code=303,
        )

    if action == "relevant" and candidate.status == "relevant":
        # Relevant is the hand-off point from discovery triage into
        # detailed source review and ChatGPT-assisted prefill.
        return RedirectResponse(
            f"/admin/discovery/{candidate_id}#chatgpt-prefill",
            status_code=303,
        )

    if action in {"relevant", "prefill"} and candidate.status == "possible_duplicate":
        return RedirectResponse(
            "/admin/discovery?" + urlencode({
                "disaster_id": candidate.disaster_id,
                "platform": platform,
                "view": "duplicates",
            }),
            status_code=303,
        )

    return RedirectResponse(
        "/admin/discovery?" + urlencode(params),
        status_code=303,
    )


@router.post("/admin/discovery/bulk-status")
async def discovery_candidates_bulk_status(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate

    form = await request.form()
    action = str(form.get("status_action") or "").strip().casefold()
    candidate_ids = [parse_int(value) for value in form.getlist("candidate_ids")]
    candidate_ids = [candidate_id for candidate_id in candidate_ids if candidate_id]
    platform = str(form.get("platform") or "facebook").strip()
    view = str(form.get("view") or "review").strip().casefold()
    q = str(form.get("q") or "").strip()
    disaster_id = parse_int(form.get("disaster_id"))

    if action not in {"relevant", "irrelevant"} or not candidate_ids:
        return RedirectResponse(
            "/admin/discovery" + (f"?disaster_id={disaster_id}&platform={platform}&view={view}" if disaster_id else ""),
            status_code=303,
        )

    with SessionLocal() as db:
        candidates = list(
            db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.id.in_(candidate_ids))
            ).all()
        )
        if disaster_id:
            candidates = [item for item in candidates if item.disaster_id == disaster_id]

        for candidate in candidates:
            candidate.status = action
            audit(
                db,
                request,
                "classify_discovery_candidate",
                "discovery_candidate",
                candidate.id,
                f"bulk status={action}",
            )
        db.commit()

    params = {"disaster_id": disaster_id or "", "platform": platform, "view": view}
    if q:
        params["q"] = q
    return RedirectResponse("/admin/discovery?" + urlencode(params), status_code=303)


@router.post("/admin/discovery/ai-prefill-relevant")
async def discovery_ai_prefill_relevant(request: Request):
    """Extract every relevant source into pending submissions for human review."""
    gate = admin_gate(request)
    if gate:
        return gate

    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    platform = str(form.get("platform") or "facebook").strip().casefold()
    if not disaster_id:
        return RedirectResponse("/admin/discovery", status_code=303)

    created = skipped = failed = 0
    with SessionLocal() as db:
        disaster = db.get(Disaster, disaster_id)
        candidates = list(db.scalars(
            select(DiscoveryCandidate)
            .where(
                DiscoveryCandidate.disaster_id == disaster_id,
                DiscoveryCandidate.platform == platform,
                DiscoveryCandidate.status == "relevant",
            )
            .order_by(DiscoveryCandidate.found_at.asc())
            .limit(100)
        ).all())
        if disaster is None:
            return HTMLResponse("Unknown disaster", status_code=404)

        for candidate in candidates:
            try:
                source_text = ""
                source_image_url = None
                ocr_text = ""
                if candidate.platform == "facebook":
                    source_text = (await discover_public_post_text(candidate.url)) or ""
                    source_image_url = await discover_public_post_image(candidate.url)
                payload = await generate_openai_candidate_prefill(
                    disaster,
                    candidate,
                    source_post_text=source_text,
                    ocr_text=ocr_text,
                    source_image_url=source_image_url,
                )
                notes = _source_notes_for_candidate(candidate, source_text, ocr_text)
                for person_data in payload.get("people") or []:
                    name = str(person_data.get("name") or "").strip()
                    if not name:
                        skipped += 1
                        continue
                    duplicate = db.scalar(select(Submission.id).where(
                        Submission.disaster_id == disaster_id,
                        Submission.social_url == candidate.url,
                        func.lower(Submission.name) == name.casefold(),
                        Submission.status != "rejected",
                    ))
                    existing_source = db.scalar(select(MissingPerson.id).join(Source).where(
                        MissingPerson.disaster_id == disaster_id,
                        MissingPerson.archived.is_(False),
                        Source.url == candidate.url,
                        func.lower(MissingPerson.name) == name.casefold(),
                    ))
                    if duplicate or existing_source or _exact_name_matches(db, disaster_id, name):
                        skipped += 1
                        continue
                    db.add(Submission(
                        disaster_id=disaster_id,
                        kind="missing_report",
                        status="pending",
                        name=name,
                        name_ne=str(person_data.get("name_ne") or "").strip() or None,
                        age=parse_int(person_data.get("age")),
                        gender=_normalize_gender(person_data.get("gender")),
                        last_seen_date=parse_date(person_data.get("last_seen_date")),
                        last_seen_time=parse_time(person_data.get("last_seen_time")),
                        last_seen_location=str(person_data.get("last_seen_location") or "").strip() or None,
                        clothing=str(person_data.get("clothing") or "").strip() or None,
                        identification_details=str(person_data.get("identification_details") or "").strip() or None,
                        public_contact_number=str(person_data.get("public_contact_number") or "").strip() or None,
                        social_url=candidate.url,
                        notes=notes,
                    ))
                    created += 1
                candidate.status = "reviewed"
            except Exception as exc:
                failed += 1
                audit(db, request, "batch_ai_prefill_failed", "discovery_candidate", candidate.id, str(exc)[:500])
        audit(db, request, "batch_ai_prefill_relevant", "disaster", disaster_id, f"created={created}; skipped={skipped}; failed={failed}")
        db.commit()

    return RedirectResponse(
        "/admin/discovery?" + urlencode({
            "disaster_id": disaster_id,
            "platform": platform,
            "view": "relevant",
            "batch_prefilled": created,
            "batch_skipped": skipped,
            "batch_failed": failed,
        }),
        status_code=303,
    )


@router.get("/admin/discovery/{candidate_id}/public-details")
async def discovery_candidate_public_details(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate

    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        disaster = db.get(Disaster, candidate.disaster_id)
        if disaster is None:
            return JSONResponse({"error": "unknown disaster"}, status_code=404)

        source_text = ""
        if candidate.platform == "facebook":
            source_text = (await discover_public_post_text(candidate.url)) or ""

        evidence_text = source_text or candidate.snippet or ""
        prefill = extract_candidate_prefill(
            candidate,
            disaster,
            source_text=source_text,
        )
        people = extract_candidate_people_names(
            candidate,
            source_text=source_text,
        )
        multiple_people = candidate_mentions_multiple_people(
            candidate,
            source_text=source_text,
        )

        return JSONResponse(
            {
                "text": evidence_text,
                "full_public_text_available": bool(source_text),
                "people": people,
                "multiple_people": multiple_people,
                "age": prefill.get("age"),
                "last_seen_location": prefill.get("last_seen_location"),
                "public_contact_number": prefill.get("public_contact_number"),
            }
        )


@router.get("/admin/discovery/{candidate_id}/duplicate-check")
def discovery_candidate_duplicate_check(
    request: Request,
    candidate_id: int,
    name: str = "",
    location: str = "",
    age: int | None = None,
    phone: str = "",
):
    gate = admin_gate(request)
    if gate:
        return gate

    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        exact = _exact_published_name_matches(db, candidate.disaster_id, name)
        pending = _pending_name_matches(db, candidate.disaster_id, name)

        people = []
        seen_ids: set[int] = set()
        for person in exact:
            if person.id in seen_ids:
                continue
            seen_ids.add(person.id)
            has_source = db.scalar(
                select(Source.id).where(
                    Source.person_id == person.id,
                    Source.url == candidate.url,
                )
            ) is not None
            if has_source:
                # Do not warn about the case created from this same source.
                continue
            people.append(
                {
                    "id": person.id,
                    "case_number": person.case_number,
                    "name": person.name,
                    "age": person.age,
                    "last_seen_location": person.last_seen_location,
                    "score": 100.0,
                    "exact_name": True,
                    "public_url": f"/person/{person.case_number}",
                    "source_already_attached": has_source,
                }
            )

        return JSONResponse(
            {
                "people": people,
                "pending": [
                    {"id": item.id, "name": item.name}
                    for item in pending[:5]
                ],
            }
        )


@router.get(
    "/admin/discovery/{candidate_id}",
    response_class=HTMLResponse,
)
async def discovery_candidate_review(
    request: Request,
    candidate_id: int,
    created: int | None = None,
    attached: int | None = None,
    batch_created: int | None = None,
    batch_published: int | None = None,
    batch_duplicates: int | None = None,
    batch_skipped: int | None = None,
    auto_prefill: int | None = None,
):
    gate = admin_gate(request)
    if gate:
        return gate

    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)

        disaster = db.get(Disaster, candidate.disaster_id)
        if disaster is None:
            return HTMLResponse("Unknown disaster", status_code=404)

        source_image_url = None
        source_post_text = ""
        ocr_text = ""
        ocr_detail = None

        if candidate.platform == "facebook":
            source_post_text = (await discover_public_post_text(candidate.url)) or ""
            source_image_url = await discover_public_post_image(candidate.url)

        if source_image_url:
            if ocr_available():
                ocr_dir = settings.upload_dir / "_ocr_preview"
                ocr_filename = await download_public_source_image(
                    source_image_url,
                    ocr_dir,
                )
                if ocr_filename:
                    local_path = ocr_dir / ocr_filename
                    result = extract_ocr_text(local_path)
                    ocr_text = result.text
                    ocr_detail = result.detail
                    try:
                        local_path.unlink(missing_ok=True)
                        ocr_dir.rmdir()
                    except OSError:
                        pass
            else:
                ocr_detail = (
                    "Local OCR is not available yet. Install Tesseract OCR "
                    "and the Nepali language data to read poster text automatically."
                )

        prefill = extract_candidate_prefill(
            candidate,
            disaster,
            ocr_text=ocr_text,
            source_text=source_post_text,
        )
        chatgpt_prefill_prompt = build_candidate_chatgpt_prefill_prompt(
            disaster,
            candidate,
            source_post_text=source_post_text,
            ocr_text=ocr_text,
        )
        detected_people = extract_candidate_people_names(
            candidate,
            source_text=source_post_text,
            ocr_text=ocr_text,
        )
        multiple_people_signal = candidate_mentions_multiple_people(
            candidate,
            source_text=source_post_text,
            ocr_text=ocr_text,
        )
        if prefill.get("name") and prefill["name"].casefold() not in {
            item.casefold() for item in detected_people
        }:
            detected_people.insert(0, prefill["name"])

        source_submission_names = _source_handled_names(db, candidate)
        remaining_people = [
            item for item in detected_people
            if item.casefold() not in source_submission_names
        ]

        if (
            created
            and remaining_people
            and str(prefill.get("name") or "").strip().casefold()
            in source_submission_names
        ):
            # After one person is created from a multi-person source, move the
            # review form to the next explicit name. Other fields remain review
            # suggestions and must still be checked by the operator.
            prefill["name"] = remaining_people[0]

        exact_duplicates = _exact_published_name_matches(
            db,
            candidate.disaster_id,
            str(prefill.get("name") or ""),
        )
        exact_duplicates = [
            person for person in exact_duplicates
            if db.scalar(
                select(Source.id).where(
                    Source.person_id == person.id,
                    Source.url == candidate.url,
                )
            ) is None
        ]
        pending_duplicates = _pending_name_matches(
            db,
            candidate.disaster_id,
            str(prefill.get("name") or ""),
        )

        db.commit()

        return render(
            request,
            "admin_discovery_review.html",
            candidate=candidate,
            prefill=prefill,
            source_image_url=source_image_url,
            source_post_text=source_post_text,
            ocr_text=ocr_text,
            ocr_detail=ocr_detail,
            detected_people=detected_people,
            remaining_people=remaining_people,
            multiple_people_signal=multiple_people_signal,
            exact_duplicates=exact_duplicates,
            pending_duplicates=pending_duplicates,
            source_submission_names=source_submission_names,
            chatgpt_prefill_prompt=chatgpt_prefill_prompt,
            openai_prefill_status=openai_prefill_status(),
            created=bool(created),
            attached=bool(attached),
            batch_created=batch_created or 0,
            batch_published=batch_published or 0,
            batch_duplicates=batch_duplicates or 0,
            batch_skipped=batch_skipped or 0,
            auto_prefill=bool(auto_prefill),
        )


@router.post("/admin/discovery/{candidate_id}/openai-prefill")
async def discovery_openai_prefill(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate

    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if candidate.status != "relevant":
            return JSONResponse(
                {"error": "Mark this source Relevant before running AI Prefill."},
                status_code=409,
            )
        disaster = db.get(Disaster, candidate.disaster_id)
        if disaster is None:
            return JSONResponse({"error": "unknown disaster"}, status_code=404)

        source_post_text = ""
        source_image_url = None
        ocr_text = ""

        if candidate.platform == "facebook":
            source_post_text = (await discover_public_post_text(candidate.url)) or ""
            source_image_url = await discover_public_post_image(candidate.url)

        # Local OCR is still useful when installed. The OpenAI request may also
        # receive the reviewed public source image, with strict instructions to
        # read written text only and never identify/infer from appearance.
        if source_image_url and ocr_available():
            ocr_dir = settings.upload_dir / "_ocr_openai_prefill"
            ocr_filename = await download_public_source_image(source_image_url, ocr_dir)
            if ocr_filename:
                local_path = ocr_dir / ocr_filename
                result = extract_ocr_text(local_path)
                ocr_text = result.text
                try:
                    local_path.unlink(missing_ok=True)
                    ocr_dir.rmdir()
                except OSError:
                    pass

        try:
            payload = await generate_openai_candidate_prefill(
                disaster,
                candidate,
                source_post_text=source_post_text,
                ocr_text=ocr_text,
                source_image_url=source_image_url,
            )
        except OpenAIPrefillError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)

        audit(
            db,
            request,
            "openai_candidate_prefill",
            "discovery_candidate",
            candidate.id,
            (
                f"model={payload.get('model')}; "
                f"people={len(payload.get('people') or [])}; "
                f"input_tokens={(payload.get('usage') or {}).get('input_tokens', 0)}; "
                f"output_tokens={(payload.get('usage') or {}).get('output_tokens', 0)}"
            ),
        )
        db.commit()
        return JSONResponse(payload)


@router.post("/admin/discovery/{candidate_id}/chatgpt-prefill/parse")
async def discovery_chatgpt_prefill_parse(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    raw = str(form.get("result_json") or "")
    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return JSONResponse({"error": "not found"}, status_code=404)
    try:
        payload = parse_candidate_chatgpt_prefill(raw)
    except ChatGPTPrefillParseError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(payload)


@router.post("/admin/discovery/{candidate_id}/skip-remaining")
async def discovery_skip_remaining(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)
        candidate.status = "reviewed"
        audit(db, request, "skip_remaining_discovery_people", "discovery_candidate", candidate.id, candidate.url)
        db.commit()
        return RedirectResponse(_next_discovery_review_url(db, candidate, "Review queue complete."), status_code=303)


@router.post("/admin/discovery/{candidate_id}/remaining/remove")
async def discovery_remove_remaining_person(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    name = str(form.get("name") or "").strip()
    source_post_text = str(form.get("source_post_text") or "").strip()
    ocr_text = str(form.get("ocr_text") or "").strip()
    if not name:
        return RedirectResponse(f"/admin/discovery/{candidate_id}", status_code=303)
    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)
        existing = db.scalar(
            select(Submission.id).where(
                Submission.disaster_id == candidate.disaster_id,
                Submission.social_url == candidate.url,
                Submission.kind == "discovery_skipped",
                func.lower(Submission.name) == name.casefold(),
            )
        )
        if existing is None:
            db.add(
                Submission(
                    disaster_id=candidate.disaster_id,
                    kind="discovery_skipped",
                    status="rejected",
                    name=name,
                    social_url=candidate.url,
                    notes="Operator removed this extracted person from review.",
                )
            )
            db.flush()
        remaining_names = _remaining_source_names(db, candidate, source_post_text, ocr_text)
        candidate.status = "relevant" if remaining_names else "reviewed"
        audit(db, request, "remove_extracted_discovery_person", "discovery_candidate", candidate.id, name)
        db.commit()
        if remaining_names:
            return RedirectResponse(f"/admin/discovery/{candidate_id}#chatgpt-prefill", status_code=303)
        return RedirectResponse(_next_discovery_review_url(db, candidate, "Review queue complete."), status_code=303)


@router.post("/admin/discovery/{candidate_id}/chatgpt-prefill/batch")
async def discovery_chatgpt_prefill_batch(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    raw = str(form.get("result_json") or "")
    source_post_text = str(form.get("source_post_text") or "").strip()
    ocr_text = str(form.get("ocr_text") or "").strip()
    save_mode = str(form.get("save_mode") or "pending").strip().casefold()
    if save_mode not in {"pending", "publish"}:
        save_mode = "pending"

    try:
        payload = parse_candidate_chatgpt_prefill(raw)
    except ChatGPTPrefillParseError as exc:
        return HTMLResponse(f"Could not parse ChatGPT prefill: {exc}", status_code=400)

    created = 0
    published = 0
    duplicates = 0
    skipped = 0

    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)
        if candidate.status in {"irrelevant", "rejected"}:
            return HTMLResponse("Restore this candidate before creating records.", status_code=409)
        disaster = db.get(Disaster, candidate.disaster_id)
        if disaster is None:
            return HTMLResponse("Unknown disaster", status_code=404)

        notes = _source_notes_for_candidate(candidate, source_post_text, ocr_text)
        for person_data in payload["people"]:
            name = str(person_data.get("name") or "").strip()
            if not name:
                skipped += 1
                continue

            existing_source_person = db.scalar(
                select(MissingPerson.id)
                .join(Source, Source.person_id == MissingPerson.id)
                .where(
                    MissingPerson.disaster_id == candidate.disaster_id,
                    Source.url == candidate.url,
                    func.lower(MissingPerson.name) == name.casefold(),
                    MissingPerson.archived.is_(False),
                )
            )
            same_source_submission = db.scalar(
                select(Submission.id).where(
                    Submission.disaster_id == candidate.disaster_id,
                    Submission.social_url == candidate.url,
                    func.lower(Submission.name) == name.casefold(),
                    Submission.status != "rejected",
                )
            )
            if existing_source_person or same_source_submission:
                skipped += 1
                continue

            # Batch mode remains fail-closed on duplicate names. Those need the
            # individual attach-vs-new decision rather than an automatic merge.
            if _exact_name_matches(db, candidate.disaster_id, name) or _pending_name_matches(
                db, candidate.disaster_id, name
            ):
                duplicates += 1
                continue

            if save_mode == "publish":
                person = MissingPerson(
                    case_number=next_case_number(db, disaster),
                    disaster_id=candidate.disaster_id,
                    name=name,
                    name_ne=str(person_data.get("name_ne") or "").strip() or None,
                    age=parse_int(person_data.get("age")),
                    gender=_normalize_gender(person_data.get("gender")),
                    photo_path=None,
                    last_seen_date=parse_date(person_data.get("last_seen_date")),
                    last_seen_time=parse_time(person_data.get("last_seen_time")),
                    last_seen_location=str(person_data.get("last_seen_location") or "").strip() or "Unknown",
                    clothing=str(person_data.get("clothing") or "").strip() or None,
                    identification_details=str(person_data.get("identification_details") or "").strip() or None,
                    public_contact_number=str(person_data.get("public_contact_number") or "").strip() or None,
                    published=True,
                )
                db.add(person)
                db.flush()
                db.add(PersonCaseState(person_id=person.id, status="missing"))
                db.add(
                    Source(
                        person_id=person.id,
                        platform=candidate.platform,
                        url=candidate.url,
                        source_text=notes,
                    )
                )
                published += 1
            else:
                db.add(
                    Submission(
                        disaster_id=candidate.disaster_id,
                        kind="missing_report",
                        status="pending",
                        name=name,
                        name_ne=str(person_data.get("name_ne") or "").strip() or None,
                        age=parse_int(person_data.get("age")),
                        gender=_normalize_gender(person_data.get("gender")),
                        photo_path=None,
                        last_seen_date=parse_date(person_data.get("last_seen_date")),
                        last_seen_time=parse_time(person_data.get("last_seen_time")),
                        last_seen_location=str(person_data.get("last_seen_location") or "").strip() or None,
                        clothing=str(person_data.get("clothing") or "").strip() or None,
                        identification_details=str(person_data.get("identification_details") or "").strip() or None,
                        public_contact_number=str(person_data.get("public_contact_number") or "").strip() or None,
                        social_url=candidate.url,
                        notes=notes,
                    )
                )
                created += 1

        remaining_names = _remaining_source_names(db, candidate, source_post_text, ocr_text)
        candidate.status = "relevant" if remaining_names else "reviewed"
        audit(
            db,
            request,
            "batch_ai_prefill_records",
            "discovery_candidate",
            candidate.id,
            (
                f"mode={save_mode}; pending={created}; published={published}; "
                f"duplicates={duplicates}; skipped={skipped}"
            ),
        )
        db.commit()

    params = urlencode(
        {
            "batch_created": created,
            "batch_published": published,
            "batch_duplicates": duplicates,
            "batch_skipped": skipped,
        }
    )
    if published and not remaining_names:
        with SessionLocal() as db:
            candidate = db.get(DiscoveryCandidate, candidate_id)
            if candidate is not None:
                return RedirectResponse(_next_discovery_review_url(db, candidate, "Review queue complete."), status_code=303)
    return RedirectResponse(f"/admin/discovery/{candidate_id}?{params}#chatgpt-prefill", status_code=303)


@router.post("/admin/discovery/{candidate_id}/submission")
async def discovery_to_submission(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate

    form = await request.form()
    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)
        if candidate.status in {"irrelevant", "rejected"}:
            return HTMLResponse(
                "Restore this discovery candidate before creating a submission.",
                status_code=409,
            )

        name = str(form.get("name") or "").strip()
        location = str(form.get("last_seen_location") or "").strip()
        save_mode = str(form.get("save_mode") or "pending").strip().casefold()
        if save_mode not in {"pending", "publish"}:
            save_mode = "pending"
        if not name or not location:
            return RedirectResponse(f"/admin/discovery/{candidate_id}", status_code=303)

        ocr_text = str(form.get("ocr_text") or "").strip()
        source_post_text = str(form.get("source_post_text") or "").strip()
        notes = _source_notes_for_candidate(candidate, source_post_text, ocr_text)

        exact_duplicates = _exact_name_matches(db, candidate.disaster_id, name)
        duplicate_action = str(form.get("duplicate_action") or "").strip().casefold()

        if exact_duplicates:
            if duplicate_action.startswith("attach:"):
                try:
                    person_id = int(duplicate_action.split(":", 1)[1])
                except ValueError:
                    return HTMLResponse("Invalid duplicate action", status_code=400)
                person = next((item for item in exact_duplicates if item.id == person_id), None)
                if person is None:
                    return HTMLResponse("Duplicate target does not match this name", status_code=409)

                existing_source = db.scalar(
                    select(Source).where(
                        Source.person_id == person.id,
                        Source.url == candidate.url,
                    )
                )
                if existing_source is None:
                    db.add(
                        Source(
                            person_id=person.id,
                            platform=candidate.platform,
                            url=candidate.url,
                            source_text=notes,
                        )
                    )
                elif notes and not existing_source.source_text:
                    existing_source.source_text = notes

                if save_mode == "publish":
                    case_state = _person_case_status_map(db, [person.id]).get(person.id, "missing")
                    if case_state == "missing":
                        person.published = True
                candidate.status = "relevant"
                audit(
                    db,
                    request,
                    "attach_discovery_source_existing_person",
                    "person",
                    person.id,
                    candidate.url,
                )
                db.commit()
                return RedirectResponse(
                    f"/admin/discovery/{candidate_id}?attached=1#person-entry-form",
                    status_code=303,
                )

            if duplicate_action != "continue":
                return HTMLResponse(
                    "Duplicate name detected. Choose the existing person to attach this source, "
                    "or explicitly confirm that this is a different person with the same name.",
                    status_code=409,
                )

        pending_duplicates = _pending_name_matches(
            db,
            candidate.disaster_id,
            name,
        )
        if pending_duplicates and duplicate_action != "continue":
            return HTMLResponse(
                "A pending submission already uses this name. Review the pending entry first, "
                "or explicitly confirm that this should be a separate entry.",
                status_code=409,
            )

        source_image_url = str(form.get("source_image_url") or "").strip()
        include_source_image = str(form.get("include_source_image") or "") == "1"
        photo_path = None

        photo_upload = form.get("photo")
        if photo_upload is not None and getattr(photo_upload, "filename", ""):
            try:
                photo_path = await save_image(photo_upload, settings.upload_dir)
            except ValueError as exc:
                return HTMLResponse(str(exc), status_code=400)
        elif include_source_image and source_image_url and is_allowed_public_image_url(source_image_url):
            photo_path = await download_public_source_image(
                source_image_url,
                settings.upload_dir,
            )

        same_source_submissions = db.scalars(
            select(Submission).where(
                Submission.disaster_id == candidate.disaster_id,
                Submission.social_url == candidate.url,
                Submission.status != "rejected",
            )
        ).all()
        existing_same_source = any(
            (item.name or "").strip().casefold() == name.casefold()
            for item in same_source_submissions
        )
        if existing_same_source:
            return HTMLResponse(
                "This person already has a submission from this exact public source.",
                status_code=409,
            )

        if save_mode == "publish":
            disaster = db.get(Disaster, candidate.disaster_id)
            if disaster is None:
                return HTMLResponse("Unknown disaster", status_code=404)
            selected_point = parse_coords(
                f"{form.get('last_seen_lat') or ''},{form.get('last_seen_lon') or ''}"
            )
            point = selected_point or (_geo_point_for_text(location) if location else None)
            person = MissingPerson(
                case_number=next_case_number(db, disaster),
                disaster_id=candidate.disaster_id,
                name=name,
                photo_path=photo_path,
                name_ne=str(form.get("name_ne") or "").strip() or None,
                age=parse_int(form.get("age")),
                gender=_normalize_gender(form.get("gender")),
                last_seen_date=parse_date(form.get("last_seen_date")),
                last_seen_time=parse_time(form.get("last_seen_time")),
                last_seen_location=location,
                last_seen_lat=point.lat if point else None,
                last_seen_lon=point.lon if point else None,
                clothing=str(form.get("clothing") or "").strip() or None,
                identification_details=str(form.get("identification_details") or "").strip() or None,
                public_contact_number=str(form.get("public_contact_number") or "").strip() or None,
                published=True,
            )
            db.add(person)
            db.flush()
            db.add(PersonCaseState(person_id=person.id, status="missing"))
            db.add(
                Source(
                    person_id=person.id,
                    platform=candidate.platform,
                    url=candidate.url,
                    source_text=notes,
                )
            )
            remaining_names = _remaining_source_names(db, candidate, source_post_text, ocr_text)
            candidate.status = "relevant" if remaining_names else "reviewed"
            audit(
                db,
                request,
                "candidate_publish_missing_person",
                "person",
                person.id,
                candidate.url,
            )
            db.commit()
            if remaining_names:
                return RedirectResponse(
                    f"/admin/discovery/{candidate_id}?created=1#person-entry-form",
                    status_code=303,
                )
            return RedirectResponse(_next_discovery_review_url(db, candidate, "Review queue complete."), status_code=303)

        point = _geo_point_for_text(location) if location else None
        sub = Submission(
            disaster_id=candidate.disaster_id,
            kind="missing_report",
            name=name,
            photo_path=photo_path,
            name_ne=str(form.get("name_ne") or "").strip() or None,
            age=parse_int(form.get("age")),
            gender=_normalize_gender(form.get("gender")),
            last_seen_date=parse_date(form.get("last_seen_date")),
            last_seen_time=parse_time(form.get("last_seen_time")),
            last_seen_location=location,
            last_seen_lat=point.lat if point else None,
            last_seen_lon=point.lon if point else None,
            clothing=str(form.get("clothing") or "").strip() or None,
            identification_details=str(form.get("identification_details") or "").strip() or None,
            public_contact_number=str(form.get("public_contact_number") or "").strip() or None,
            social_url=candidate.url,
            notes=notes,
        )
        db.add(sub)

        candidate.status = "relevant"
        db.flush()
        audit(
            db,
            request,
            "candidate_to_submission",
            "submission",
            sub.id,
            candidate.url,
        )
        db.commit()

    return RedirectResponse(
        f"/admin/discovery/{candidate_id}?created=1#person-entry-form",
        status_code=303,
    )


@router.get(
    "/admin/ai-review",
    response_class=HTMLResponse,
)
def discovery_ai_review_page(
    request: Request,
    disaster_id: int,
    platform: str = "facebook",
):
    gate = admin_gate(request)

    if gate:
        return gate

    with SessionLocal() as db:
        disaster = db.get(
            Disaster,
            disaster_id,
        )

        if disaster is None:
            return HTMLResponse(
                "Unknown disaster",
                status_code=404,
            )

        candidates = list(
            db.scalars(
                select(DiscoveryCandidate)
                .where(
                    DiscoveryCandidate.disaster_id
                    == disaster.id,
                    DiscoveryCandidate.platform
                    == platform,
                    DiscoveryCandidate.status.in_(
                        ["new", "needs_ai", "relevant"]
                    ),
                )
                .order_by(
                    DiscoveryCandidate.found_at.desc()
                )
                .limit(100)
            ).all()
        )

        prompt = build_free_ai_review_prompt(
            disaster,
            candidates,
        )

        return render(
            request,
            "admin_ai_review.html",
            disaster=disaster,
            platform=platform,
            candidates=candidates,
            prompt=prompt,
        )


@router.post(
    "/admin/ai-review/import"
)
async def discovery_ai_review_import(
    request: Request,
):
    gate = admin_gate(request)

    if gate:
        return gate

    form = await request.form()

    disaster_id = parse_int(
        form.get("disaster_id")
    )

    platform = str(
        form.get("platform") or "facebook"
    ).strip()

    raw_result = str(
        form.get("result_json") or ""
    ).strip()

    if not disaster_id or not raw_result:
        return HTMLResponse(
            "Missing AI review data",
            status_code=400,
        )

    try:
        results = parse_free_ai_review(
            raw_result
        )
    except ValueError:
        return HTMLResponse(
            "Invalid AI review JSON. "
            "Return to Free AI Review and paste "
            "the JSON response exactly.",
            status_code=400,
        )

    created = 0
    rejected = 0
    uncertain = 0

    downloaded_images: dict[str, str | None] = {}

    with SessionLocal() as db:
        disaster = db.get(
            Disaster,
            disaster_id,
        )

        if disaster is None:
            return HTMLResponse(
                "Unknown disaster",
                status_code=404,
            )

        for result in results:
            candidate = db.get(
                DiscoveryCandidate,
                result["candidate_id"],
            )

            # AI output never gets authority to change
            # disaster/source identity.
            if candidate is None:
                continue

            if (
                candidate.disaster_id
                != disaster.id
            ):
                continue

            if candidate.platform != platform:
                continue

            if candidate.status not in {
                "new",
                "needs_ai",
                "relevant",
            }:
                continue

            decision = result["decision"]

            if decision == "reject":
                candidate.status = "irrelevant"
                rejected += 1
                continue

            if decision == "uncertain":
                uncertain += 1
                continue

            accepted_person = False

            for person_data in result["people"]:
                name = str(
                    person_data.get("name")
                    or ""
                ).strip()

                if not name:
                    continue

                accepted_person = True

                existing = db.scalar(
                    select(Submission.id).where(
                        Submission.disaster_id
                        == disaster.id,
                        Submission.social_url
                        == candidate.url,
                        Submission.name
                        == name,
                    )
                )

                if existing:
                    continue

                image_url = str(
                    person_data.get(
                        "image_url"
                    )
                    or ""
                ).strip()

                photo_path = None

                if (
                    image_url
                    and is_allowed_public_image_url(
                        image_url
                    )
                ):
                    if (
                        image_url
                        not in downloaded_images
                    ):
                        downloaded_images[
                            image_url
                        ] = (
                            await download_public_source_image(
                                image_url,
                                settings.upload_dir,
                            )
                        )

                    photo_path = (
                        downloaded_images[
                            image_url
                        ]
                    )

                reason = result.get(
                    "reason"
                ) or ""

                confidence = result.get(
                    "confidence"
                )

                notes = (
                    candidate.snippet
                    or ""
                ).strip()

                ai_note = (
                    f"Free AI review: {reason}"
                )

                if confidence is not None:
                    ai_note += (
                        f" | confidence={confidence}"
                    )

                if (
                    image_url
                    and is_allowed_public_image_url(
                        image_url
                    )
                ):
                    ai_note += (
                        f" | source_image_url={image_url}"
                    )

                if notes:
                    notes = (
                        notes
                        + "\n\n"
                        + ai_note
                    )
                else:
                    notes = ai_note

                submission = Submission(
                    disaster_id=disaster.id,
                    kind="missing_report",
                    name=name,
                    photo_path=photo_path,
                    name_ne=(
                        str(
                            person_data.get(
                                "name_ne"
                            )
                            or ""
                        ).strip()
                        or None
                    ),
                    age=parse_int(
                        person_data.get("age")
                    ),
                    gender=_normalize_gender(person_data.get("gender")),
                    last_seen_date=parse_date(
                        person_data.get(
                            "last_seen_date"
                        )
                    ),
                    last_seen_time=parse_time(
                        person_data.get(
                            "last_seen_time"
                        )
                    ),
                    last_seen_location=(
                        str(
                            person_data.get(
                                "last_seen_location"
                            )
                            or ""
                        ).strip()
                        or None
                    ),
                    clothing=(
                        str(
                            person_data.get(
                                "clothing"
                            )
                            or ""
                        ).strip()
                        or None
                    ),
                    identification_details=(
                        str(
                            person_data.get(
                                "identification_details"
                            )
                            or ""
                        ).strip()
                        or None
                    ),
                    public_contact_number=(
                        str(
                            person_data.get(
                                "public_contact_number"
                            )
                            or ""
                        ).strip()
                        or None
                    ),
                    social_url=candidate.url,
                    notes=notes,
                )

                db.add(submission)
                created += 1

            if accepted_person:
                candidate.status = "reviewed"

        audit(
            db,
            request,
            "import_free_ai_review",
            "disaster",
            disaster.id,
            (
                f"platform={platform}; "
                f"submissions={created}; "
                f"rejected={rejected}; "
                f"uncertain={uncertain}"
            ),
        )

        db.commit()

    return RedirectResponse(
        "/admin/submissions",
        status_code=303,
    )


@router.get("/admin/export", response_class=HTMLResponse)
def export_page(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all())
        return render(request, "admin_export.html", disasters=disasters)


@router.get("/admin/export/{file_type}")
def export_data(request: Request, file_type: str, disaster_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    if file_type not in {"csv", "xlsx"}:
        return HTMLResponse("Unsupported export", status_code=400)
    with SessionLocal() as db:
        disaster = db.get(Disaster, disaster_id)
        if disaster is None:
            return HTMLResponse("Unknown disaster", status_code=404)
        if file_type == "csv":
            data = build_csv(db, disaster_id)
            media = "text/csv; charset=utf-8"
        else:
            data = build_xlsx(db, disaster_id)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        audit(db, request, "export", "disaster", disaster_id, file_type)
        db.commit()
        filename = f"{disaster.code.lower()}-missing-people.{file_type}"
        return Response(
            data,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get("/admin/people/{person_id}/share-card")
def share_card(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person is None:
            return HTMLResponse("Not found", status_code=404)
        image = build_share_card(person)
        audit(db, request, "generate_share_card", "person", person.id)
        db.commit()
        return Response(
            image,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="{person.case_number}.png"'},
        )

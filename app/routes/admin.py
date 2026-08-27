from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import SessionLocal
from ..models import AdminUser, Disaster, DiscoveryCandidate, MissingPerson, Source, Submission
from ..security import verify_password
from ..services.discovery import discover_candidates, generate_queries, google_search_url
from ..services.duplicates import find_duplicates
from ..services.exports import build_csv, build_xlsx
from ..services.normalization import affected_location_match, canonicalize_url, detect_platform
from ..services.share_cards import build_share_card
from .common import admin_gate, audit, next_case_number, parse_date, parse_int, parse_time, render

router = APIRouter()


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
        request.session["admin"] = admin.username
        audit(db, request, "login", "admin", admin.id)
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
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
        }
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all())
        return render(request, "admin_dashboard.html", stats=stats, disasters=disasters)


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
        disaster = Disaster(
            code=code,
            name=name,
            disaster_type=str(form.get("disaster_type") or "flood").strip(),
            start_date=start_date,
            affected_locations=str(form.get("affected_locations") or "").strip(),
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
        disaster.name = str(form.get("name") or disaster.name).strip()
        disaster.disaster_type = str(form.get("disaster_type") or disaster.disaster_type).strip()
        disaster.affected_locations = str(form.get("affected_locations") or "").strip()
        disaster.active = str(form.get("active") or "") == "on"
        audit(db, request, "update_event", "disaster", disaster.id, disaster.name)
        db.commit()
    return RedirectResponse("/admin/events", status_code=303)


@router.get("/admin/people", response_class=HTMLResponse)
def admin_people(request: Request, disaster_id: int | None = None, q: str = ""):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        disasters = list(db.scalars(select(Disaster).order_by(Disaster.start_date.desc())).all())
        stmt = (
            select(MissingPerson)
            .options(selectinload(MissingPerson.sources))
            .order_by(MissingPerson.created_at.desc())
        )
        if disaster_id:
            stmt = stmt.where(MissingPerson.disaster_id == disaster_id)
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
        return render(
            request,
            "admin_people.html",
            people=people,
            disasters=disasters,
            selected_disaster=disaster_id,
            q=q,
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
        person.gender = str(form.get("gender") or "").strip() or None
        person.last_seen_date = parse_date(form.get("last_seen_date"))
        person.last_seen_time = parse_time(form.get("last_seen_time"))
        person.last_seen_location = str(form.get("last_seen_location") or "").strip()
        person.clothing = str(form.get("clothing") or "").strip() or None
        person.identification_details = str(form.get("identification_details") or "").strip() or None
        person.public_contact_number = str(form.get("public_contact_number") or "").strip() or None
        person.residential_address_private = str(form.get("residential_address_private") or "").strip() or None
        audit(db, request, "edit_person", "person", person.id)
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/publish")
def admin_publish(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person:
            person.published = not person.published
            audit(db, request, "publish_toggle", "person", person.id, str(person.published))
            db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


@router.post("/admin/people/{person_id}/archive")
def admin_archive(request: Request, person_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        person = db.get(MissingPerson, person_id)
        if person:
            person.archived = True
            person.published = False
            audit(db, request, "archive_person", "person", person.id)
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


@router.post("/admin/submissions/{submission_id}/approve-new")
def approve_submission_new(request: Request, submission_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
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
            published=False,
        )
        db.add(person)
        db.flush()
        sub.person_id = person.id
        sub.status = "approved"
        if sub.social_url:
            db.add(
                Source(
                    person_id=person.id,
                    platform=detect_platform(sub.social_url),
                    url=sub.social_url,
                    source_text=sub.notes,
                )
            )
        audit(db, request, "approve_submission_new", "person", person.id, f"submission={sub.id}")
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
        audit(db, request, "attach_submission", "person", person.id, f"submission={sub.id}")
        db.commit()
    return RedirectResponse(f"/admin/people/{person_id}", status_code=303)


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
def discovery_page(request: Request, disaster_id: int | None = None, platform: str = "facebook"):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        disasters = list(
            db.scalars(select(Disaster).order_by(Disaster.active.desc(), Disaster.start_date.desc())).all()
        )
        selected = (
            db.get(Disaster, disaster_id)
            if disaster_id
            else next((d for d in disasters if d.active), disasters[0] if disasters else None)
        )
        queries = generate_queries(selected, platform=platform) if selected else []
        candidates = (
            list(
                db.scalars(
                    select(DiscoveryCandidate)
                    .where(DiscoveryCandidate.disaster_id == selected.id)
                    .order_by(DiscoveryCandidate.found_at.desc())
                    .limit(200)
                ).all()
            )
            if selected
            else []
        )
        return render(
            request,
            "admin_discovery.html",
            disasters=disasters,
            selected=selected,
            platform=platform,
            queries=[(q, google_search_url(q, selected.start_date)) for q in queries] if selected else [],
            candidates=candidates,
            bot_message=None,
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


@router.post("/admin/discovery/manual")
async def discovery_manual(request: Request):
    gate = admin_gate(request)
    if gate:
        return gate
    form = await request.form()
    disaster_id = parse_int(form.get("disaster_id"))
    url = canonicalize_url(str(form.get("url") or ""))
    platform = str(form.get("platform") or "facebook")
    if not disaster_id or not url:
        return RedirectResponse("/admin/discovery", status_code=303)
    with SessionLocal() as db:
        existing = db.scalar(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.disaster_id == disaster_id, DiscoveryCandidate.url == url
            )
        )
        if existing is None:
            candidate = DiscoveryCandidate(
                disaster_id=disaster_id,
                platform=platform,
                query="manual-url",
                url=url,
                title=str(form.get("title") or "").strip() or None,
                snippet=str(form.get("snippet") or "").strip() or None,
            )
            db.add(candidate)
            db.flush()
            audit(db, request, "add_manual_candidate", "discovery_candidate", candidate.id, url)
            db.commit()
    return RedirectResponse(f"/admin/discovery?disaster_id={disaster_id}&platform={platform}", status_code=303)


@router.get("/admin/discovery/{candidate_id}", response_class=HTMLResponse)
def discovery_candidate_review(request: Request, candidate_id: int):
    gate = admin_gate(request)
    if gate:
        return gate
    with SessionLocal() as db:
        candidate = db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            return HTMLResponse("Not found", status_code=404)
        return render(request, "admin_discovery_review.html", candidate=candidate)


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
        name = str(form.get("name") or "").strip()
        location = str(form.get("last_seen_location") or "").strip()
        if not name or not location:
            return RedirectResponse(f"/admin/discovery/{candidate_id}", status_code=303)
        sub = Submission(
            disaster_id=candidate.disaster_id,
            kind="missing_report",
            name=name,
            name_ne=str(form.get("name_ne") or "").strip() or None,
            age=parse_int(form.get("age")),
            gender=str(form.get("gender") or "").strip() or None,
            last_seen_date=parse_date(form.get("last_seen_date")),
            last_seen_location=location,
            clothing=str(form.get("clothing") or "").strip() or None,
            identification_details=str(form.get("identification_details") or "").strip() or None,
            public_contact_number=str(form.get("public_contact_number") or "").strip() or None,
            social_url=candidate.url,
            notes=candidate.snippet,
        )
        db.add(sub)
        candidate.status = "reviewed"
        db.flush()
        audit(db, request, "candidate_to_submission", "submission", sub.id, candidate.url)
        db.commit()
    return RedirectResponse("/admin/submissions", status_code=303)


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

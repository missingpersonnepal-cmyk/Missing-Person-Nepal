from datetime import date

from app import bot_runner
from app.database import SessionLocal
from app.models import Disaster


def test_bot_runner_uses_active_event_and_commits(monkeypatch, capsys):
    with SessionLocal() as db:
        db.add(
            Disaster(
                code="RF",
                name="Rasuwa Flood",
                disaster_type="flood",
                start_date=date(2026, 8, 26),
                affected_locations="Rasuwa\nTimure",
                active=True,
            )
        )
        db.commit()

    monkeypatch.setattr("sys.argv", ["bot_runner", "--event", "RF", "--platform", "facebook"])
    monkeypatch.setattr(bot_runner, "discover_candidates", lambda db, disaster, platform: 3)
    assert bot_runner.main() == 0
    output = capsys.readouterr().out
    assert "event=RF" in output
    assert "new_candidates=3" in output


def test_bot_runner_returns_two_when_no_event(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["bot_runner", "--event", "NOPE"])
    assert bot_runner.main() == 2
    assert "No matching active disaster" in capsys.readouterr().out

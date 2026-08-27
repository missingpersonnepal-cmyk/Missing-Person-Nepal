from app.services.normalization import affected_location_match


def test_affected_location_match():
    affected = "Rasuwa\nTimure\nRasuwagadhi"
    assert affected_location_match("Timure, Rasuwa", affected)
    assert affected_location_match("Near Rasuwagadhi bridge", affected)
    assert not affected_location_match("Pokhara", affected)

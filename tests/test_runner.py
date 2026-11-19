from models.novel import WebNovelRequest
from runner import ResumableRunner


def test_run_checkpoint_can_be_updated_after_restarting(tmp_path, monkeypatch):
    monkeypatch.setattr("runner.create_client", lambda: None)
    request = WebNovelRequest(
        genre="fantasy",
        core_pleasure="growth",
        protagonist_name="Hero",
        protagonist_background="An apprentice",
        golden_finger="A hidden library",
    )
    runner = ResumableRunner("checkpoint-test", request, tmp_path)
    runner._update_run(status="running", completed_chapters=0)
    runner._update_run(completed_chapters=1)

    resumed = ResumableRunner("checkpoint-test", request, tmp_path)
    assert resumed._load("run")["completed_chapters"] == 1
    resumed._update_run(status="paused", completed_chapters=2)

    saved = runner._load("run")
    assert saved["status"] == "paused"
    assert saved["completed_chapters"] == 2
    assert not (tmp_path / "run.tmp").exists()

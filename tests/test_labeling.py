"""The labeling page's server: blind, local only, and saving as it goes."""

import json
import threading

import httpx
import pytest

from baitreel import labels, workspace
from baitreel.labeling import LabelingServer
from tests.conftest import make_transcript

TRANSCRIPT = make_transcript(
    "Hello this is Officer Daniel Hart.", "Do not tell anyone about this call."
)


@pytest.fixture
def server(home, bait, tmp_path):
    recording = tmp_path / "call.wav"
    recording.write_bytes(bytes(range(256)) * 40)  # not real audio: only the bytes matter here
    bait = bait.model_copy(update={"source_path": str(recording), "duration": 30.0})
    # Baitreel has already run on this call. The page must still not see its answers.
    folder = workspace.bait_dir(bait.id)
    folder.mkdir(parents=True)
    (folder / "flags.json").write_text(
        json.dumps([{"tactic": "the-badge", "marker": "TOOL-ANSWER-7731"}])
    )
    mine = labels.open_labels(bait.id, "Sam", TRANSCRIPT)
    running = LabelingServer(bait, TRANSCRIPT, mine)
    thread = threading.Thread(target=running.httpd.serve_forever, daemon=True)
    thread.start()
    yield running
    running.stop()


def test_listens_only_on_this_computer(server):
    assert server.httpd.server_address[0] == "127.0.0.1"


def test_refuses_requests_without_the_token_or_from_another_host(server):
    base = f"http://127.0.0.1:{server.port}"
    assert httpx.get(f"{base}/api/call").status_code == 404
    assert httpx.get(f"{base}/wrong-token/api/call").status_code == 404
    # A web page that rebinds its own domain to 127.0.0.1 still sends its own Host header.
    rebound = httpx.get(server.url + "api/call", headers={"Host": "evil.example:80"})
    assert rebound.status_code == 404


def test_the_page_gets_the_transcript_but_not_baitreels_answers(server):
    call = httpx.get(server.url + "api/call").json()
    assert [line["id"] for line in call["lines"]] == [0, 1]
    # Unmasked: the labeler must be able to see every detail to mark it.
    assert call["lines"][0]["words"][4]["text"] == "Daniel"
    assert {t["id"] for t in call["tactics"]} >= {"the-badge", "the-hush"}
    assert call["tool_ran_first"] is True
    text = json.dumps(call)
    assert "TOOL-ANSWER-7731" not in text and "redaction" not in text
    assert httpx.get(server.url).headers["content-type"].startswith("text/html")


def test_saves_labels_and_rejects_bad_ones(server):
    good = {
        "flags": [{"tactic": "the-hush", "start": 3.0, "end": 5.0}],
        "details": [{"start": 1.2, "end": 1.9, "kind": "name"}],
    }
    assert httpx.put(server.url + "api/labels", json=good).status_code == 200
    (saved,) = labels.load_all(server.bait.id)
    assert saved.flags[0].tactic == "the-hush" and saved.details[0].kind == "name"
    assert not saved.finished

    invented = {"flags": [{"tactic": "the-whisper", "start": 1, "end": 2}], "details": []}
    assert httpx.put(server.url + "api/labels", json=invented).status_code == 400
    outside = {"flags": [], "details": [{"start": 50, "end": 60, "kind": "name"}]}
    assert httpx.put(server.url + "api/labels", json=outside).status_code == 400
    # A plain form post from another site cannot change the labels.
    sneaky = httpx.put(server.url + "api/labels", content=json.dumps(good).encode(),
                       headers={"Content-Type": "text/plain"})  # fmt: skip
    assert sneaky.status_code == 415


def test_finishing_marks_the_labels_and_stops_the_page(server):
    body = {"flags": [], "details": [], "finished": True}
    assert httpx.put(server.url + "api/labels", json=body).json()["finished"] is True
    assert httpx.post(server.url + "api/done").status_code == 200
    assert server.finished.wait(2)
    assert labels.load_all(server.bait.id)[0].finished


def test_audio_supports_seeking(server):
    whole = httpx.get(server.url + "audio")
    assert whole.status_code == 200 and len(whole.content) == 256 * 40
    part = httpx.get(server.url + "audio", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == bytes(range(10, 20))
    assert part.headers["content-range"] == f"bytes 10-19/{256 * 40}"
    tail = httpx.get(server.url + "audio", headers={"Range": "bytes=-4"})
    assert tail.content == bytes(range(252, 256))

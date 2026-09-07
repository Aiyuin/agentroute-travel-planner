"""Run inside the backend container to verify auth, SSE, and checkpoint recovery."""

import argparse
import json
import os
import urllib.error
import urllib.request


def request(path, body=None, authenticated=True):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = "Bearer " + os.environ["AUTH_SECRET"]
    data = None if body is None else json.dumps(body).encode()
    return urllib.request.urlopen(
        urllib.request.Request("http://127.0.0.1:8080" + path, data=data, headers=headers),
        timeout=150,
    )


def verify(phase, thread_id):
    assert request("/health", authenticated=False).status == 200
    try:
        request("/info", authenticated=False)
    except urllib.error.HTTPError as error:
        assert error.code in (401, 403)
    else:
        raise AssertionError("Unauthenticated API request was accepted")
    info = json.load(request("/info"))
    assert info["default_agent"] == "travel-assistant"
    if phase == "create":
        first = json.load(
            request(
                "/travel-assistant/invoke",
                {
                    "message": "我想去杭州玩三天。",
                    "thread_id": thread_id,
                },
            )
        )
        assert "预算" in first["content"]
        events = []
        with request(
            "/travel-assistant/stream",
            {
                "message": "每人1500元，不含往返大交通，喜欢自然风景。",
                "thread_id": thread_id,
            },
        ) as response:
            for line in response:
                line = line.decode().strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    events.append(json.loads(line[6:]))
        assert not any(event["type"] == "error" for event in events)
        messages = [event["content"]["content"] for event in events if event["type"] == "message"]
        assert messages and "估算总额" in messages[-1]
        assert "默认 2 晚" in messages[-1]
        print("PASS: authenticated multi-turn planning and SSE final result")
    history = json.load(request("/travel-assistant/history", {"thread_id": thread_id}))
    assert len(history["messages"]) == 4
    assert "估算总额" in history["messages"][-1]["content"]
    print(f"PASS: {phase} history contains four messages; auth enabled")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["create", "restore"])
    parser.add_argument("thread_id")
    args = parser.parse_args()
    verify(args.phase, args.thread_id)

"""Conversation participants: the message:update route guard, set_participants,
and mention-driven participant additions."""

from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)


async def _me_id(client, tokens) -> str:
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _add_member(client, owner_tokens, ws, email: str, role_name: str) -> dict:
    roles = (await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))).json()
    role = next(r for r in roles if r["name"] == role_name)
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": email, "role_id": role["id"]},
            headers=ws_headers(owner_tokens, ws["id"]),
        )
    ).json()
    tokens = await register_user(client, email)
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(tokens),
    )
    return {"tokens": tokens, "id": await _me_id(client, tokens)}


async def _setup(client, *, role_name: str = "editor"):
    """Owner with a workspace plus two joined members."""
    owner = await register_user(client, "owner@example.com")
    ws = await create_workspace(client, owner, "Acme Corp")
    owner_id = await _me_id(client, owner)
    members = [
        await _add_member(client, owner, ws, "a@example.com", role_name),
        await _add_member(client, owner, ws, "b@example.com", role_name),
    ]
    return {"tokens": owner, "id": owner_id}, ws, members


async def _open_conversation(client, owner, ws, members):
    resp = await client.post(
        "/api/v1/conversations",
        json={
            "title": "Kickoff",
            "participant_user_ids": [members[0]["id"], members[1]["id"]],
            "initial_message": "hello",
        },
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ids(conversation: dict) -> set[str]:
    return {p["id"] for p in conversation["participants"]}


# ------------------------------------------------------------- set_participants


async def test_owner_removes_a_participant(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)
    path = f"/api/v1/conversations/{conv['id']}/participants"

    resp = await app_client.patch(
        path,
        json={"participant_user_ids": [owner["id"], members[0]["id"]]},
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == {owner["id"], members[0]["id"]}

    # The removed user loses access; the kept one keeps it.
    gone = await app_client.get(
        f"/api/v1/conversations/{conv['id']}", headers=ws_headers(members[1]["tokens"], ws["id"])
    )
    assert gone.status_code == 403, gone.text
    kept = await app_client.get(
        f"/api/v1/conversations/{conv['id']}", headers=ws_headers(members[0]["tokens"], ws["id"])
    )
    assert kept.status_code == 200, kept.text


async def test_owner_adds_a_participant(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)
    outsider = await _add_member(app_client, owner["tokens"], ws, "c@example.com", "viewer")

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={
            "participant_user_ids": [
                owner["id"],
                members[0]["id"],
                members[1]["id"],
                outsider["id"],
            ]
        },
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert outsider["id"] in _ids(resp.json())


async def test_editor_can_edit_participants(app_client):
    owner, ws, members = await _setup(app_client, role_name="editor")
    conv = await _open_conversation(app_client, owner, ws, members)

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={"participant_user_ids": [members[0]["id"]]},
        headers=ws_headers(members[0]["tokens"], ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == {members[0]["id"]}


async def test_viewer_cannot_edit_participants(app_client):
    owner, ws, members = await _setup(app_client, role_name="viewer")
    conv = await _open_conversation(app_client, owner, ws, members)

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={"participant_user_ids": [members[0]["id"]]},
        headers=ws_headers(members[0]["tokens"], ws["id"]),
    )
    assert resp.status_code == 403, resp.text
    assert "message:update" in resp.text


async def test_cannot_remove_yourself(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={"participant_user_ids": [members[0]["id"], members[1]["id"]]},
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 400, resp.text
    assert "remove yourself" in resp.text


async def test_non_participant_cannot_edit_participants(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)
    outsider = await _add_member(app_client, owner["tokens"], ws, "c@example.com", "editor")

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={"participant_user_ids": [owner["id"]]},
        headers=ws_headers(outsider["tokens"], ws["id"]),
    )
    assert resp.status_code == 403, resp.text


async def test_cannot_add_non_member_user(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)
    stranger = await register_user(app_client, "stranger@example.com")

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={"participant_user_ids": [owner["id"], await _me_id(app_client, stranger)]},
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 400, resp.text
    assert "not members of this workspace" in resp.text


async def test_participant_list_is_deduplicated(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)

    resp = await app_client.patch(
        f"/api/v1/conversations/{conv['id']}/participants",
        json={
            "participant_user_ids": [
                owner["id"],
                members[0]["id"],
                members[0]["id"],
                "  ",
                members[0]["id"],
            ]
        },
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == {owner["id"], members[0]["id"]}


# -------------------------------------------------------------------- mentions


async def test_mention_adds_the_user_to_the_conversation(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)
    outsider = await _add_member(app_client, owner["tokens"], ws, "c@example.com", "viewer")

    before = await app_client.get(
        f"/api/v1/conversations/{conv['id']}", headers=ws_headers(outsider["tokens"], ws["id"])
    )
    assert before.status_code == 403, before.text

    resp = await app_client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"body": "hi @Cee", "mentioned_user_ids": [outsider["id"]]},
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["body"] == "hi @Cee"

    after = await app_client.get(
        f"/api/v1/conversations/{conv['id']}", headers=ws_headers(outsider["tokens"], ws["id"])
    )
    assert after.status_code == 200, after.text
    assert outsider["id"] in _ids(after.json())


async def test_mention_of_a_non_member_is_rejected(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)
    stranger = await register_user(app_client, "stranger@example.com")

    resp = await app_client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"body": "hi", "mentioned_user_ids": [await _me_id(app_client, stranger)]},
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 400, resp.text
    assert "not members of this workspace" in resp.text


async def test_message_without_mentions_leaves_participants_alone(app_client):
    owner, ws, members = await _setup(app_client)
    conv = await _open_conversation(app_client, owner, ws, members)

    resp = await app_client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"body": "plain reply"},
        headers=ws_headers(owner["tokens"], ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    after = await app_client.get(
        f"/api/v1/conversations/{conv['id']}", headers=ws_headers(owner["tokens"], ws["id"])
    )
    assert _ids(after.json()) == {owner["id"], members[0]["id"], members[1]["id"]}

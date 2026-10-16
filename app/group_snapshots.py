"""Normalize group member snapshots and persist deterministic differences."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlmodel import select

from .db import get_session
from .event_center import emit_event
from .models import GroupConversation, GroupMember, GroupMemberEvent, GroupSnapshot


def _normalized_member(value: dict) -> dict:
    member_id = str(value.get("member_id") or value.get("user_id") or value.get("uid") or "").strip()
    if not member_id:
        raise ValueError("群成员缺少 member_id/user_id/uid")
    return {
        "member_id": member_id,
        "nickname": str(value.get("nickname") or value.get("name") or "").strip(),
        "avatar": str(value.get("avatar") or "").strip(),
        "role": str(value.get("role") or "member").strip() or "member",
    }


def ingest_group_snapshot(*, platform: str, account_id: int, group_id: str,
                          group_name: str, members: list[dict]) -> dict:
    now = datetime.utcnow()
    normalized = {_normalized_member(value)["member_id"]: _normalized_member(value)
                  for value in members}
    canonical = json.dumps(
        [normalized[key] for key in sorted(normalized)],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    with get_session() as session:
        group = session.exec(select(GroupConversation).where(
            GroupConversation.platform == platform,
            GroupConversation.account_id == account_id,
            GroupConversation.group_id == group_id)).first()
        if group is None:
            group = GroupConversation(
                platform=platform, account_id=account_id,
                group_id=group_id, name=group_name)

        current_rows = session.exec(select(GroupMember).where(
            GroupMember.platform == platform,
            GroupMember.account_id == account_id,
            GroupMember.group_id == group_id)).all()
        current = {row.member_id: row for row in current_rows}
        joined = sorted(set(normalized) - {key for key, row in current.items() if row.active})
        left = sorted({key for key, row in current.items() if row.active} - set(normalized))
        changed: list[str] = []
        before_values: dict[str, dict] = {}

        for member_id, value in normalized.items():
            row = current.get(member_id)
            if row is None:
                row = GroupMember(
                    platform=platform, account_id=account_id,
                    group_id=group_id, member_id=member_id,
                    first_seen_at=now)
            before = {"member_id": member_id, "nickname": row.nickname,
                      "avatar": row.avatar, "role": row.role}
            if row.active and member_id not in joined and any(
                    before[key] != value[key] for key in ("nickname", "avatar", "role")):
                changed.append(member_id)
                before_values[member_id] = before
            row.nickname, row.avatar, row.role = value["nickname"], value["avatar"], value["role"]
            row.active, row.left_at, row.last_seen_at = True, None, now
            row.raw_json = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            session.add(row)

        for member_id in left:
            current[member_id].active = False
            current[member_id].left_at = now
            session.add(current[member_id])

        snapshot = GroupSnapshot(
            platform=platform, account_id=account_id, group_id=group_id,
            member_count=len(normalized), joined_count=len(joined),
            left_count=len(left), changed_count=len(changed), payload_hash=payload_hash)
        session.add(snapshot)
        session.flush()
        for member_id in joined:
            session.add(GroupMemberEvent(
                snapshot_id=snapshot.id, platform=platform, account_id=account_id,
                group_id=group_id, member_id=member_id, change_type="joined",
                after_json=json.dumps(normalized[member_id], ensure_ascii=False)))
        for member_id in left:
            before = {"member_id": member_id, "nickname": current[member_id].nickname,
                      "avatar": current[member_id].avatar, "role": current[member_id].role}
            session.add(GroupMemberEvent(
                snapshot_id=snapshot.id, platform=platform, account_id=account_id,
                group_id=group_id, member_id=member_id, change_type="left",
                before_json=json.dumps(before, ensure_ascii=False)))
        for member_id in changed:
            session.add(GroupMemberEvent(
                snapshot_id=snapshot.id, platform=platform, account_id=account_id,
                group_id=group_id, member_id=member_id, change_type="changed",
                before_json=json.dumps(before_values[member_id], ensure_ascii=False),
                after_json=json.dumps(normalized[member_id], ensure_ascii=False)))
        group.name = group_name or group.name
        group.member_count = len(normalized)
        group.last_snapshot_at = now
        session.add(group)
        session.commit()
        snapshot_id = int(snapshot.id)

    result = {"snapshot_id": snapshot_id, "member_count": len(normalized),
              "joined": joined, "left": left, "changed": sorted(changed),
              "payload_hash": payload_hash}
    emit_event("group.members.changed", {
        "platform": platform, "account_id": account_id,
        "group_id": group_id, "group_name": group_name, **result,
    }, aggregate_type="group", aggregate_id=group_id)
    return result

"""运行事件：装袋成功/业务拒绝都落 pack_events，只读接口可检索。"""

from sqlalchemy import func, select

from app.models.models import (
    BagItem,
    DeliveryRoute,
    PackBag,
    PackEvent,
    RejectRecord,
    SubscriberStop,
)


def _make_route(db, name, max_weight=8.0, max_volume=20.0):
    route = DeliveryRoute(name=name, max_weight_kg=max_weight, max_volume_l=max_volume)
    db.add(route)
    db.flush()
    return route


def _add_stop(db, route_id, seq, weight, volume, name=None):
    db.add(
        SubscriberStop(
            route_id=route_id,
            seq=seq,
            name=name or f"stop-{seq}",
            weight_kg=weight,
            volume_l=volume,
        )
    )
    db.flush()


def test_successful_pack_writes_packed_event(client, db_session):
    route = _make_route(db_session, "纯成功线", max_weight=10.0, max_volume=20.0)
    _add_stop(db_session, route.id, 1, 2.0, 3.0)
    _add_stop(db_session, route.id, 2, 3.0, 4.0)
    db_session.commit()

    resp = client.post("/api/pack", json={"route_id": route.id})
    assert resp.status_code == 200

    events = db_session.scalars(select(PackEvent)).all()
    assert len(events) == 1
    ev = events[0]
    assert ev.route_id == route.id
    assert ev.bag_count == 1
    assert ev.reject_count == 0
    assert ev.outcome == "packed"
    assert ev.created_at is not None

    # 事件不替代袋明细：袋与袋明细行仍在
    bag_rows = db_session.scalars(select(PackBag).where(PackBag.route_id == route.id)).all()
    assert len(bag_rows) == 1
    item_count = db_session.scalar(
        select(func.count()).select_from(BagItem).where(BagItem.bag_id == bag_rows[0].id)
    )
    assert item_count == 2


def test_reject_outcome_event_when_oversized(client, db_session):
    route = _make_route(db_session, "含拒收线", max_weight=5.0, max_volume=10.0)
    _add_stop(db_session, route.id, 1, 9.0, 1.0)  # 超重 -> 拒收
    _add_stop(db_session, route.id, 2, 1.0, 1.0)
    db_session.commit()

    resp = client.post("/api/pack", json={"route_id": route.id})
    assert resp.status_code == 200

    events = db_session.scalars(select(PackEvent)).all()
    assert len(events) == 1
    ev = events[0]
    assert ev.route_id == route.id
    assert ev.bag_count == 1
    assert ev.reject_count == 1
    assert ev.outcome == "rejected"
    assert ev.created_at is not None

    # 拒收表仍有对应拒收行
    rej = db_session.scalars(select(RejectRecord)).all()
    assert len(rej) == 1
    assert rej[0].route_id == route.id


def test_two_consecutive_packs_same_route_yield_two_distinguishable_events(client, db_session):
    route = _make_route(db_session, "重复装袋线", max_weight=10.0, max_volume=20.0)
    _add_stop(db_session, route.id, 1, 2.0, 3.0)
    db_session.commit()

    assert client.post("/api/pack", json={"route_id": route.id}).status_code == 200
    assert client.post("/api/pack", json={"route_id": route.id}).status_code == 200

    events = db_session.scalars(
        select(PackEvent).where(PackEvent.route_id == route.id).order_by(PackEvent.id)
    ).all()
    assert len(events) == 2
    assert events[0].id != events[1].id
    for ev in events:
        assert ev.outcome == "packed"
        assert ev.bag_count == 1
        assert ev.reject_count == 0
    assert events[1].created_at >= events[0].created_at

    # 袋明细按最新一次装袋重建（每袋含该订户点），事件表不动
    bag_rows = db_session.scalars(select(PackBag).where(PackBag.route_id == route.id)).all()
    assert len(bag_rows) == 1
    item_count = db_session.scalar(
        select(func.count()).select_from(BagItem).where(BagItem.bag_id == bag_rows[0].id)
    )
    assert item_count == 1


def test_get_events_ordered_by_route_desc(client, db_session):
    r1 = _make_route(db_session, "一线", max_weight=10.0, max_volume=20.0)
    r2 = _make_route(db_session, "二线", max_weight=10.0, max_volume=20.0)
    _add_stop(db_session, r1.id, 1, 1.0, 1.0)
    _add_stop(db_session, r2.id, 1, 1.0, 1.0)
    db_session.commit()

    client.post("/api/pack", json={"route_id": r1.id})
    client.post("/api/pack", json={"route_id": r2.id})
    client.post("/api/pack", json={"route_id": r2.id})  # r2 再来一次

    resp = client.get("/api/events")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    # 按路线倒序：r2 的两条在前，同路线新事件在前
    assert [r["route_id"] for r in rows] == [r2.id, r2.id, r1.id]
    assert rows[0]["id"] > rows[1]["id"]
    for r in rows:
        assert set(r) == {
            "id",
            "route_id",
            "bag_count",
            "reject_count",
            "outcome",
            "created_at",
        }
        assert r["bag_count"] == 1
        assert r["reject_count"] == 0
        assert r["outcome"] == "packed"

    # route_id 过滤
    only_r1 = client.get(f"/api/events?route_id={r1.id}").json()
    assert [r["id"] for r in only_r1] == [
        e.id
        for e in db_session.scalars(
            select(PackEvent).where(PackEvent.route_id == r1.id)
        ).all()
    ]

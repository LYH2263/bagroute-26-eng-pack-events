"""装袋运行事件：写入路径旁路落库 + 只读倒序查询接口。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import (
    OUTCOME_PACKED,
    OUTCOME_REJECTED,
    BagItem,
    DeliveryRoute,
    PackBag,
    PackEvent,
    RejectRecord,
    SubscriberStop,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db):
    # 不用 with 包裹，避免触发 lifespan 连接真实库；表已由 db fixture 建好
    return TestClient(app)


def make_route(db, name="测试线", max_w=8.0, max_v=20.0, stops=()):
    route = DeliveryRoute(name=name, max_weight_kg=max_w, max_volume_l=max_v)
    db.add(route)
    db.flush()
    for i, (w, v) in enumerate(stops, start=1):
        db.add(SubscriberStop(route_id=route.id, seq=i, name=f"点{i}", weight_kg=w, volume_l=v))
    db.commit()
    return route


def events_of(db, route_id):
    return db.scalars(select(PackEvent).where(PackEvent.route_id == route_id)).all()


def test_pack_success_writes_event_and_keeps_bag_details(client, db):
    route = make_route(db, stops=[(2.0, 3.0), (2.5, 3.0)])
    resp = client.post("/api/pack", json={"route_id": route.id})
    assert resp.status_code == 200
    bags = resp.json()
    assert len(bags) == 1

    events = events_of(db, route.id)
    assert len(events) == 1
    ev = events[0]
    assert ev.id is not None
    assert ev.route_id == route.id
    assert ev.bag_count == len(bags)
    assert ev.reject_count == 0
    assert ev.outcome == OUTCOME_PACKED
    assert ev.created_at is not None

    # 事件不替代袋明细：袋行与袋内条目仍在
    bag_rows = db.scalars(select(PackBag).where(PackBag.route_id == route.id)).all()
    assert len(bag_rows) == ev.bag_count
    item_rows = db.scalars(
        select(BagItem).where(BagItem.bag_id.in_([b.id for b in bag_rows]))
    ).all()
    assert len(item_rows) == 2


def test_pack_with_reject_stop_records_event_and_reject_row(client, db):
    route = make_route(db, max_w=5.0, max_v=5.0, stops=[(9.0, 1.0), (1.0, 1.0)])
    resp = client.post("/api/pack", json={"route_id": route.id})
    assert resp.status_code == 200

    events = events_of(db, route.id)
    assert len(events) == 1
    ev = events[0]
    assert ev.outcome == OUTCOME_PACKED
    assert ev.bag_count == 1
    assert ev.reject_count == 1

    # 事件不替代拒收表：拒收行仍在
    rejects = db.scalars(select(RejectRecord).where(RejectRecord.route_id == route.id)).all()
    assert len(rejects) == 1
    assert rejects[0].stop_name == "点1"


def test_two_packs_same_route_produce_two_distinguishable_events(client, db):
    route = make_route(db, stops=[(2.0, 3.0), (2.5, 3.0)])
    assert client.post("/api/pack", json={"route_id": route.id}).status_code == 200
    assert client.post("/api/pack", json={"route_id": route.id}).status_code == 200

    events = events_of(db, route.id)
    assert len(events) == 2
    assert events[0].id != events[1].id

    resp = client.get("/api/events", params={"route_id": route.id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # 倒序：新事件在前
    assert body[0]["id"] > body[1]["id"]
    for item in body:
        assert item["route_id"] == route.id
        assert item["bag_count"] == 1
        assert item["reject_count"] == 0
        assert item["outcome"] == OUTCOME_PACKED
        assert item["created_at"]

    # 重复装袋后袋明细仍只有最新一代，事件表才是累计的
    bag_rows = db.scalars(select(PackBag).where(PackBag.route_id == route.id)).all()
    assert len(bag_rows) == 1


def test_empty_route_business_rejection_writes_event(client, db):
    route = make_route(db, stops=[])
    resp = client.post("/api/pack", json={"route_id": route.id})
    assert resp.status_code == 422

    events = events_of(db, route.id)
    assert len(events) == 1
    ev = events[0]
    assert ev.route_id == route.id
    assert ev.outcome == OUTCOME_REJECTED
    assert ev.bag_count == 0
    assert ev.reject_count == 0
    assert ev.created_at is not None

    assert db.scalars(select(PackBag).where(PackBag.route_id == route.id)).all() == []


def test_events_endpoint_filters_by_route_descending(client, db):
    r1 = make_route(db, name="甲线", stops=[(1.0, 1.0)])
    r2 = make_route(db, name="乙线", stops=[(1.0, 1.0)])
    client.post("/api/pack", json={"route_id": r1.id})
    client.post("/api/pack", json={"route_id": r2.id})
    client.post("/api/pack", json={"route_id": r1.id})

    body = client.get("/api/events", params={"route_id": r1.id}).json()
    assert len(body) == 2
    assert all(item["route_id"] == r1.id for item in body)
    assert body[0]["created_at"] >= body[1]["created_at"]
    assert body[0]["id"] > body[1]["id"]

    body2 = client.get("/api/events", params={"route_id": r2.id}).json()
    assert len(body2) == 1
    assert body2[0]["route_id"] == r2.id

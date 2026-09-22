# BagRoute

投递装袋：按路线订户顺序装袋，重量与体积双约束，超限拒收。

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4300 |
| API | http://localhost:9300 |
| API 文档 | http://localhost:9300/docs |
| Postgres | localhost:5444 |

健康检查：`GET http://localhost:9300/api/health`

## 页面

- `/routes` — 路线
- `/stops` — 订户点
- `/pack` — 装袋
- `/bags` — 袋明细
- `/rejects` — 拒收
- `/weights` — 袋重

## 使用说明

1. 查看路线与订户点顺序。
2. 在装袋页选择路线执行双约束装袋。
3. 袋明细与袋重查看结果，拒收页查看超限订户。

## 装袋事件

每次装袋成功（`packed`）或业务拒绝（`rejected`，如空路线）都会旁路追加一条运行事件到 `pack_events` 表，只增不删；同一路线连装两次产生两条可区分事件。事件不替代袋明细与拒收表。

| 字段 | 含义 |
| --- | --- |
| id | 事件主键，自增 |
| route_id | 路线 ID |
| bag_count | 本次装出袋数 |
| reject_count | 本次拒收订户数 |
| outcome | `packed` 装袋成功 / `rejected` 业务拒绝 |
| created_at | 事件时间（UTC） |

只读查询：`GET http://localhost:9300/api/events?route_id=<路线ID>`，按时间倒序返回该路线事件。

## 开发与测试

```bash
docker compose exec api pytest -q
```

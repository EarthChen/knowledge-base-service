"""Test: multi-batch feedback-loop enrichment (>10 entities = 2 feedback rounds)."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from llm.gateway_client import GatewayTaskClient


def _make_item(name: str, desc: str) -> dict[str, str]:
    return {
        "file": "src/main/java/com/example/shop/ShopService.java",
        "name": name,
        "signature": f"public void {name}(...)",
        "docstring": desc,
        "code_snippet": f"public void {name}() {{ /* ... */ }}",
    }


async def main() -> None:
    client = GatewayTaskClient(
        gateway_ws_url="ws://localhost:9090/acp/v1/connect",
        gateway_http_url="http://localhost:9090",
        api_key="sk-admin-test",
        model="gemini-3-flash",
        timeout=120,
    )

    items = [
        _make_item("addToCart", "将商品添加到购物车"),
        _make_item("removeFromCart", "从购物车中移除商品"),
        _make_item("updateCartQuantity", "更新购物车中商品的数量"),
        _make_item("getCartItems", "获取购物车商品列表"),
        _make_item("calculateCartTotal", "计算购物车总价"),
        _make_item("applyCoupon", "应用优惠券到购物车"),
        _make_item("removeCoupon", "移除购物车中的优惠券"),
        _make_item("checkInventory", "检查商品库存是否充足"),
        _make_item("reserveInventory", "预留商品库存"),
        _make_item("releaseInventory", "释放预留的商品库存"),
        _make_item("createPayment", "创建支付订单"),
        _make_item("processRefund", "处理退款"),
    ]

    print(f"\n=== Testing multi-batch enrichment: {len(items)} items (expect 2 feedback rounds) ===\n")
    results = await client.enrich_batch(items)

    for item, summary in zip(items, results):
        print(f"  {item['name']}: {summary[:60]}..." if summary else f"  {item['name']}: (empty)")

    success_count = sum(1 for r in results if r)
    print(f"\n=== Test complete: {success_count}/{len(items)} entities enriched ===")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider
    llm = MagicMock(spec=LLMProvider)
    llm.complete_json = AsyncMock(return_value={
        "flow_name": "用户下单",
        "description": "处理用户创建订单的完整流程",
        "category": "交易",
        "steps": [
            {"function": "createOrder", "role": "entry_point", "order": 1},
            {"function": "validateStock", "role": "validator", "order": 2},
            {"function": "processPayment", "role": "processor", "order": 3},
        ],
        "sub_flows": [],
    })
    return llm


@pytest.fixture
def mock_store():
    store = MagicMock()
    return store


class TestBusinessFlowInferencer:
    @pytest.mark.asyncio
    async def test_infer_from_call_chain(self, mock_llm, mock_store):
        from indexer.business_flow_inferencer import BusinessFlowInferencer
        inferencer = BusinessFlowInferencer(llm=mock_llm, store=mock_store)
        chain = [
            {"name": "createOrder", "business_summary": "创建订单入口", "file": "order.py"},
            {"name": "validateStock", "business_summary": "验证库存", "file": "stock.py"},
            {"name": "processPayment", "business_summary": "处理支付", "file": "pay.py"},
        ]
        result = await inferencer.infer_from_chain(chain)
        assert result is not None
        assert result["flow_name"] == "用户下单"
        assert len(result["steps"]) == 3

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_llm, mock_store):
        from indexer.business_flow_inferencer import BusinessFlowInferencer
        mock_llm.complete_json = AsyncMock(side_effect=Exception("LLM error"))
        inferencer = BusinessFlowInferencer(llm=mock_llm, store=mock_store)
        chain = [{"name": "func", "business_summary": "test", "file": "a.py"}]
        result = await inferencer.infer_from_chain(chain)
        assert result is None

    @pytest.mark.asyncio
    async def test_chain_text_formatting(self, mock_llm, mock_store):
        from indexer.business_flow_inferencer import BusinessFlowInferencer
        inferencer = BusinessFlowInferencer(llm=mock_llm, store=mock_store)
        chain = [
            {"name": "a", "business_summary": "desc_a", "file": "x.py"},
            {"name": "b", "file": "y.py"},
        ]
        result = await inferencer.infer_from_chain(chain)
        assert result is not None
        call_args = mock_llm.complete_json.call_args[0][0]
        assert "a (desc_a)" in call_args[0]["content"]
        assert "→ b (N/A)" in call_args[0]["content"]

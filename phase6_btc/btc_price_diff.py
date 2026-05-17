import asyncio
import json
import time
import websockets

# 配置交易对
SYMBOL_SPOT = "btcfdusd"
SYMBOL_PERP = "btcusdt"

URL_SPOT = f"wss://stream.binance.com:9443/ws/{SYMBOL_SPOT}@bookTicker"
URL_PERP = f"wss://fstream.binance.com/ws/{SYMBOL_PERP}@bookTicker"

# 全局状态存储
state = {
    "spot_bid_p": 0.0,
    "spot_bid_q": 0.0,
    "perp_ask_p": 0.0,
    "perp_ask_q": 0.0,
    "is_ordering": False  # 订单锁
}

def get_ms_timestamp():
    return int(time.time() * 1000)

async def simulate_order(t0, target_spot_bid, target_perp_ask, expected_net_spread):
    """独立的模拟订单执行协程"""
    # 格式要求：[T0: 发单]
    print(f"[{t0}: 发单] 试图套利... 预期净利: {expected_net_spread:.2f} | 延迟等待中...")
    
    # 模拟 20ms 的网络与机房处理延迟
    await asyncio.sleep(0.02) 
    
    # 获取 20ms 后的切片数据
    t_settle = get_ms_timestamp()
    current_spot_bid = state["spot_bid_p"]
    current_perp_ask = state["perp_ask_p"]
    current_exec_qty = min(state["spot_bid_q"], state["perp_ask_q"])
    
    # 判定逻辑：价格没有变得更差，且依然有深度
    success = (current_spot_bid >= target_spot_bid and 
               current_perp_ask <= target_perp_ask and 
               current_exec_qty >= 0.01)
    
    result_str = "成功抢到" if success else "失败错过"
    
    # 格式要求：[T0+20ms: 结算]
    print(f"[{t_settle}: 结算] 结果: [{result_str}] | 实际撮合价格: Perp {current_perp_ask:.2f} Spot {current_spot_bid:.2f}\n")
    
    # 冷却 100ms 避免在同一个信号上重复多次开火
    await asyncio.sleep(0.1)
    state["is_ordering"] = False

async def handle_stream(url, market_type):
    async for websocket in websockets.connect(url):
        try:
            async for message in websocket:
                data = json.loads(message)
                
                # 正确提取并存入全局状态
                if market_type == "spot":
                    state["spot_bid_p"] = float(data['b']) # Best Bid Price
                    state["spot_bid_q"] = float(data['B']) # Best Bid Qty
                else:
                    state["perp_ask_p"] = float(data['a']) # Best Ask Price
                    state["perp_ask_q"] = float(data['A']) # Best Ask Qty
                
                # 触发逻辑
                if state["spot_bid_p"] > 0 and state["perp_ask_p"] > 0:
                    spread = state["spot_bid_p"] - state["perp_ask_p"]
                    exec_qty = min(state["spot_bid_q"], state["perp_ask_q"])
                    
                    # 扣除手续费 (万8双边)
                    fee_cost = state["spot_bid_p"] * 0.0008
                    net_spread = spread - fee_cost
                    
                    # 检查阈值且当前没有正在处理的订单
                    if net_spread > 10 and exec_qty >= 0.01 and not state["is_ordering"]:
                        state["is_ordering"] = True
                        t0 = get_ms_timestamp()
                        # 开启异步结算任务
                        asyncio.create_task(
                            simulate_order(t0, state["spot_bid_p"], state["perp_ask_p"], net_spread)
                        )

        except websockets.ConnectionClosed:
            continue
        except Exception as e:
            print(f"Error in {market_type}: {e}")
            break

async def main():
    print("高频狙击系统启动 | 延迟模拟: 20ms | 触发条件: 净利>10 且 深度>=0.01")
    print("等待猎物出现...")
    print("-" * 80)
    
    await asyncio.gather(
        handle_stream(URL_PERP, "perp"),
        handle_stream(URL_SPOT, "spot")
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n监控已结束")
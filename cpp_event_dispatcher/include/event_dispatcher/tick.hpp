#pragma once

#include <cstdint>
#include <type_traits>

namespace event_dispatcher {

/// 交易所 Tick（POD，可原地写入，便于网络层零拷贝入池）
struct alignas(64) Tick {
  std::uint64_t exchange_ts_ns{0};  ///< 交易所时间戳（纳秒，用于业务排序/对账）
  std::uint64_t recv_ts_ns{0};      ///< 本地接收时间（纳秒，可选）
  std::uint32_t instrument_id{0};
  double bid_price{0.0};
  double ask_price{0.0};
  double bid_qty{0.0};
  double ask_qty{0.0};
  std::uint32_t sequence{0};  ///< 交易所序列号（若提供）
};

static_assert(std::is_trivially_destructible_v<Tick>);

}  // namespace event_dispatcher

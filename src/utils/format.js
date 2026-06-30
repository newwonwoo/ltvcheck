// 금액 포맷 유틸

export const won = (n) => n.toLocaleString("ko-KR") + "원";

export const eok = (n) => {
  const e = Math.floor(n / 100000000);
  const m = Math.round((n % 100000000) / 10000);
  let s = "";
  if (e > 0) s += e + "억 ";
  if (m > 0) s += m.toLocaleString("ko-KR") + "만";
  return (s.trim() || "0") + "원";
};

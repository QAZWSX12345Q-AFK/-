import json
import requests
import os
from datetime import date
from string import Template

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        cfg = load_config()
        state = {}
        for fund in cfg["funds"]:
            state[fund["code"]] = {
                "shares": fund["initial_shares"],
                "total_cost": fund["initial_cost"],
                "last_update": None
            }
        return state

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def get_fund_nav(fund_code):
    """
    使用天天基金官方净值API
    """
    url = f"http://fund.eastmoney.com/f10/F10DataApi.aspx?type=lsjz&code={fund_code}&page=1&per=1"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        data = resp.text
        # 返回格式：var apidata = { ... };
        # 提取JSON部分
        import re
        json_match = re.search(r'var apidata\s*=\s*({.*?});', data, re.S)
        if not json_match:
            print(f"未找到API数据，代码 {fund_code}")
            return None
        json_str = json_match.group(1)
        # 修复可能的JSON格式问题（例如日期字段带引号）
        json_str = json_str.replace('"', '"')  # 确保引号正确
        # 手动解析，因为可能包含中文
        try:
            api_data = json.loads(json_str)
        except:
            # 如果解析失败，尝试使用eval（不推荐但可行）
            # 更安全的方式是直接正则提取
            # 我们直接用正则提取净值
            nav_match = re.search(r'"dwjz":"([\d.]+)"', data)
            name_match = re.search(r'"FCODE":"([^"]+)"', data)  # 名称在另一个字段
            date_match = re.search(r'"FSRQ":"([\d-]+)"', data)
            if nav_match and date_match:
                return {
                    "dwjz": nav_match.group(1),
                    "name": fund_code,  # 名称从配置取
                    "jzrq": date_match.group(1),
                    "gszzl": "0.00"
                }
            else:
                print(f"正则提取失败，代码 {fund_code}")
                return None
        # 如果json解析成功，则从api_data中提取
        # api_data结构: {"Data": [{"DWJZ": "1.2345", "FSRQ": "2026-09-09"}]}
        records = api_data.get("Data", [])
        if records and len(records) > 0:
            latest = records[0]
            nav = latest.get("DWJZ")
            nav_date = latest.get("FSRQ")
            if nav and nav_date:
                return {
                    "dwjz": nav,
                    "name": fund_code,
                    "jzrq": nav_date,
                    "gszzl": "0.00"
                }
        print(f"无记录，代码 {fund_code}")
        return None
    except Exception as e:
        print(f"请求异常: {e}")
        return None

def main():
    cfg = load_config()
    state = load_state()
    today = str(date.today())
    results = []
    total_cost_all = 0.0
    total_value_all = 0.0

    for fund in cfg["funds"]:
        code = fund["code"]
        daily = fund["daily_amount"]
        nav_data = get_fund_nav(code)
        if not nav_data:
            print(f"跳过 {code}，数据获取失败")
            continue

        nav = float(nav_data["dwjz"])
        nav_date = nav_data["jzrq"]
        fund_name = fund.get("name", code)

        st = state.get(code, {"shares": 0.0, "total_cost": 0.0, "last_update": None})

        if daily > 0 and st.get("last_update") != today:
            new_shares = daily / nav
            st["shares"] += new_shares
            st["total_cost"] += daily
            st["last_update"] = today
            print(f"{fund_name} 今日定投 {daily} 元，新增份额 {new_shares:.4f}")

        current_value = st["shares"] * nav
        profit = current_value - st["total_cost"]
        rate = (profit / st["total_cost"] * 100) if st["total_cost"] > 0 else 0.0

        state[code] = st

        results.append({
            "code": code,
            "name": fund_name,
            "nav": nav,
            "nav_date": nav_date,
            "shares": st["shares"],
            "total_cost": st["total_cost"],
            "current_value": current_value,
            "profit": profit,
            "rate": rate,
            "daily_amount": daily
        })

        total_cost_all += st["total_cost"]
        total_value_all += current_value

    total_profit_all = total_value_all - total_cost_all
    total_rate_all = (total_profit_all / total_cost_all * 100) if total_cost_all > 0 else 0.0

    save_state(state)

    with open("index_template.html", "r", encoding="utf-8") as f:
        template = Template(f.read())

    rows_html = ""
    for r in results:
        profit_class = "profit-positive" if r["profit"] >= 0 else "profit-negative"
        rate_class = "profit-positive" if r["rate"] >= 0 else "profit-negative"
        rows_html += f"""
        <div class="fund-item">
            <div class="fund-name">{r['name']} ({r['code']})</div>
            <div class="row"><span class="label">最新净值</span><span class="value">{r['nav']:.4f} ({r['nav_date']})</span></div>
            <div class="row"><span class="label">持有份额</span><span class="value">{r['shares']:.2f}</span></div>
            <div class="row"><span class="label">投入成本</span><span class="value">¥{r['total_cost']:.2f}</span></div>
            <div class="row"><span class="label">当前市值</span><span class="value">¥{r['current_value']:.2f}</span></div>
            <div class="row"><span class="label">收益</span><span class="value {profit_class}">{r['profit']:+.2f}</span></div>
            <div class="row"><span class="label">收益率</span><span class="value {rate_class}">{r['rate']:+.2f}%</span></div>
        </div>
        <hr>
        """

    html_content = template.safe_substitute(
        rows=rows_html,
        total_cost=f"{total_cost_all:.2f}",
        total_value=f"{total_value_all:.2f}",
        total_profit=f"{total_profit_all:+.2f}",
        total_rate=f"{total_rate_all:+.2f}",
        update_date=date.today().strftime("%Y-%m-%d")
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    print("✅ 报告生成完成！")

if __name__ == "__main__":
    main()

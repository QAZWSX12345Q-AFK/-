import json
import requests
import re
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
    从天天基金详情页解析最新净值和日期
    """
    url = f"http://fund.eastmoney.com/fund.html?fundcode={fund_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        html = resp.text

        # 打印部分内容用于调试（可删除）
        # print(html[:500])

        # 提取基金名称（从 <title> 或 h1）
        name_match = re.search(r'<title>(.*?)基金</title>', html)
        fund_name = name_match.group(1).strip() if name_match else fund_code

        # 提取单位净值 - 常见格式：<td class="tor bold" style="color:#f00;">1.2345</td>
        # 或 <span class="ui_num">1.2345</span>
        nav_match = re.search(r'单位净值</td>\s*<td[^>]*>([\d.]+)</td>', html, re.S)
        if not nav_match:
            nav_match = re.search(r'单位净值.*?<span[^>]*>([\d.]+)</span>', html, re.S)
        if not nav_match:
            nav_match = re.search(r'<span class="ui_num">([\d.]+)</span>', html)
        if not nav_match:
            # 尝试搜索 "净值" 后的数字
            nav_match = re.search(r'净值.*?(\d+\.\d+)', html)

        if not nav_match:
            print(f"未找到净值，代码 {fund_code}")
            return None

        nav = nav_match.group(1)

        # 提取净值日期 - 常见：净值日期</td><td>2026-09-09</td>
        date_match = re.search(r'净值日期</td>\s*<td[^>]*>([\d-]+)</td>', html, re.S)
        if not date_match:
            date_match = re.search(r'净值日期.*?(\d{4}-\d{2}-\d{2})', html, re.S)
        nav_date = date_match.group(1) if date_match else date.today().strftime("%Y-%m-%d")

        return {
            "dwjz": nav,
            "name": fund_name,
            "jzrq": nav_date,
            "gszzl": "0.00"
        }
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
        fund_name = nav_data.get("name", fund["name"])

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

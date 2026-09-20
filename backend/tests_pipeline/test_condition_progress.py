"""条件×平台进度台账（抓尽制模型）测试。"""
import app.session.scrape_sessions as ss


def test_progress_roundtrip_and_exhaustion(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", str(tmp_path / "t.db"))
    ss.init_scrape_sessions_table()

    # 初始 (0, 0)
    assert ss.get_condition_progress("AI应用", "广州", "15-20K", "51job") == (0, 0)
    assert ss.is_exhausted(0, 0) is False  # 分母未知不算抓尽

    # 第一轮：入库 5，校准分母 20
    ss.report_condition_round("AI应用", "广州", "15-20K", "51job", 5, 20)
    assert ss.get_condition_progress("AI应用", "广州", "15-20K", "51job") == (5, 20)
    assert ss.is_exhausted(5, 20) is False

    # 第二轮：入库 15 → 分子追平分母 → 抓尽
    ss.report_condition_round("AI应用", "广州", "15-20K", "51job", 15, 20)
    scraped, predicted = ss.get_condition_progress("AI应用", "广州", "15-20K", "51job")
    assert (scraped, predicted) == (20, 20)
    assert ss.is_exhausted(scraped, predicted) is True

    # 分母会校准：平台总数变多 → 又变为未抓尽
    ss.report_condition_round("AI应用", "广州", "15-20K", "51job", 0, 25)
    scraped, predicted = ss.get_condition_progress("AI应用", "广州", "15-20K", "51job")
    assert (scraped, predicted) == (20, 25)
    assert ss.is_exhausted(scraped, predicted) is False

    # 无分母的回写：只累加分子
    ss.report_condition_round("BOSS词", "广州", "不限", "boss", 3, None)
    assert ss.get_condition_progress("BOSS词", "广州", "不限", "boss") == (3, 0)

    # 列表接口能看到所有行
    rows = ss.list_condition_progress()
    keys = {(r["keyword"], r["platform"]) for r in rows}
    assert ("AI应用", "51job") in keys and ("BOSS词", "boss") in keys

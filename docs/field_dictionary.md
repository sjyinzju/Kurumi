# 完整字段字典

来源定义取本地保存的官方说明，未联网复核；未确认单位明确标注，不能从数值大小猜测。每表均覆盖契约字段和所有有效分区实际字段并集，实际类型为空表示本次未观察到。NULL分母是当前逻辑行；Raw全量schema尚未重扫，样本和schema_registry见supplement.json。

## trade_cal

交易日历；路径 `E:\QuantData\10_canonical\trade_cal`；自然键 `exchange,cal_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 9386/9386 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 9386/9386 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 9386/9386 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/9386 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 9386/9386 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| cal_date | str | string | 日历日期 | YYYYMMDD | 是 | 0/9386 |
| exchange | str | string | 交易所 SSE上交所 SZSE深交所 | 未单独确认；参见含义/来源定义 | 是 | 0/9386 |
| is_open | str | string | 是否交易 0休市 1交易 | 未单独确认；参见含义/来源定义 |  | 0/9386 |
| pretrade_date | str | string | 上一个交易日 | 未单独确认；参见含义/来源定义 |  | 0/9386 |

## stock_basic

股票列表；路径 `E:\QuantData\10_canonical\stock_basic`；自然键 `ts_code`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 5907/5907 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 5907/5907 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 5907/5907 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/5907 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 5907/5907 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| act_ent_type | str | string | 实控人企业性质 | 未单独确认；参见含义/来源定义 |  | 65/5907 |
| act_name | str | string | 实控人名称 | 未单独确认；参见含义/来源定义 |  | 9/5907 |
| area | str | string | 地域 | 未单独确认；参见含义/来源定义 |  | 333/5907 |
| cnspell | str | string | 拼音缩写 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| curr_type | str | string | 交易货币 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| delist_date | str | string | 退市日期 | YYYYMMDD |  | 5568/5907 |
| enname | str | string | 英文全称 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| exchange | str | string | 交易所代码 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| fullname | str | string | 股票全称 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| industry | str | string | 所属行业 | 未单独确认；参见含义/来源定义 |  | 333/5907 |
| is_hs | str | string | 是否沪深港通标的，N否 H沪股通 S深股通 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| list_date | str | string | 上市日期 | YYYYMMDD |  | 0/5907 |
| list_status | str | string | 上市状态 L上市 D退市 G过会未交易 P暂停上市 UN未上市 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| market | str | string | 市场类型（主板/创业板/科创板/CDR） | 未单独确认；参见含义/来源定义 |  | 1/5907 |
| name | str | string | 股票名称 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| symbol | str | string | 股票代码 | 未单独确认；参见含义/来源定义 |  | 0/5907 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/5907 |

## fund_basic

基金列表；路径 `E:\QuantData\10_canonical\fund_basic`；自然键 `ts_code`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2912/2912 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2912/2912 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2912/2912 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 107/2912 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2912/2912 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| benchmark | str | string | 业绩比较基准 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| c_fee | float | double | 托管费 | 未单独确认；参见含义/来源定义 |  | 680/2912 |
| custodian | str | string | 托管人 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| delist_date | str | string | 退市日期 | YYYYMMDD |  | 2286/2912 |
| due_date | str | string | 到期日期 | YYYYMMDD |  | 2235/2912 |
| duration_year | float | double | 存续期 | 未单独确认；参见含义/来源定义 |  | 2236/2912 |
| exp_return | float | double | 预期收益率 | 未单独确认；参见含义/来源定义 |  | 2912/2912 |
| found_date | str | string | 成立日期 | YYYYMMDD |  | 0/2912 |
| fund_type | str | string | 投资类型 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| invest_type | str | string | 投资风格 | 未单独确认；参见含义/来源定义 |  | 392/2912 |
| issue_amount | float | double | 发行份额(亿) | 未单独确认；参见含义/来源定义 |  | 526/2912 |
| issue_date | str | string | 发行日期 | YYYYMMDD |  | 288/2912 |
| list_date | str | string | 上市时间 | 未单独确认；参见含义/来源定义 |  | 107/2912 |
| m_fee | float | double | 管理费 | 未单独确认；参见含义/来源定义 |  | 771/2912 |
| management | str | string | 管理人 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| market | str | string | E场内O场外 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| min_amount | float | double | 起点金额(万元) | 万元 |  | 288/2912 |
| name | str | string | 简称 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| p_value | float | double | 面值 | 未单独确认；参见含义/来源定义 |  | 24/2912 |
| purc_startdate | str | string | 日常申购起始日 | 未单独确认；参见含义/来源定义 |  | 567/2912 |
| redm_startdate | str | string | 日常赎回起始日 | 未单独确认；参见含义/来源定义 |  | 563/2912 |
| status | str | string | 存续状态D摘牌/已到期 I发行 L已上市/存续中 | 未单独确认；参见含义/来源定义 |  | 0/2912 |
| trustee | str | string | 受托人 | 未单独确认；参见含义/来源定义 |  | 2912/2912 |
| ts_code | str | string | 基金代码 | 未单独确认；参见含义/来源定义 | 是 | 0/2912 |
| type | str | string | 基金类型 | 未单独确认；参见含义/来源定义 |  | 24/2912 |

## index_basic

指数基本信息；路径 `E:\QuantData\10_canonical\index_basic`；自然键 `ts_code`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 10604/10604 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 10604/10604 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| _event_available_at | 元数据 | timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 10604/10604 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 22/10604 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 10604/10604 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| base_date | str | string | 基期 | 未单独确认；参见含义/来源定义 |  | 24/10604 |
| base_point | float | double | 基点 | 未单独确认；参见含义/来源定义 |  | 26/10604 |
| category | str | string | 指数类别 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| desc | str | string | 描述 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| exp_date | str | string | 终止日期 | YYYYMMDD |  | 9976/10604 |
| fullname | str | string | 指数全称 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| index_type | str | null | 指数风格 | 未单独确认；参见含义/来源定义 |  | 10604/10604 |
| list_date | str | string | 发布日期 | YYYYMMDD |  | 22/10604 |
| market | str | string | 市场 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| name | str | string | 简称 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| publisher | str | string | 发布方 | 未单独确认；参见含义/来源定义 |  | 0/10604 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/10604 |
| weight_rule | str | string | 加权方式 | 未单独确认；参见含义/来源定义 |  | 177/10604 |

## index_classify

申万行业分类；路径 `E:\QuantData\10_canonical\index_classify`；自然键 `index_code,src`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 870/870 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 870/870 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/870 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/870 |
| _event_available_at | 元数据 | timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 870/870 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 870/870 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/870 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 870/870 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| index_code | str | string | 指数代码 | 未单独确认；参见含义/来源定义 | 是 | 0/870 |
| industry_code | str | string | 行业代码 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| industry_name | str | string | 行业名称 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| is_pub | str | string | 是否发布了指数 | 未单独确认；参见含义/来源定义 |  | 359/870 |
| level | str | string | 行业层级 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| parent_code | str | string | 父级代码 | 未单独确认；参见含义/来源定义 |  | 0/870 |
| src | str | string | 行业分类（SW申万） | 未单独确认；参见含义/来源定义 | 是 | 0/870 |

## namechange

股票曾用名；路径 `E:\QuantData\10_canonical\namechange`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 14218/14218 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1/14218 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 14218/14218 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/14218 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 14218/14218 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 1/14218 |
| change_reason | str | string | 变更原因 | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| end_date | str | string | 结束日期 | YYYYMMDD |  | 5910/14218 |
| name | str | string | 证券名称 | 未单独确认；参见含义/来源定义 |  | 0/14218 |
| start_date | str | string | 开始日期 | YYYYMMDD |  | 0/14218 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/14218 |

## stock_company

上市公司基本信息；路径 `E:\QuantData\10_canonical\stock_company`；自然键 `ts_code`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6294/6294 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6294/6294 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 6294/6294 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 6294/6294 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 6294/6294 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| business_scope | str | string | 经营范围 | 未单独确认；参见含义/来源定义 |  | 4/6294 |
| chairman | str | string | 法人代表 | 未单独确认；参见含义/来源定义 |  | 3/6294 |
| city | str | string | 所在城市 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| com_id | str | string | 统一社会信用代码 | 未单独确认；参见含义/来源定义 |  | 27/6294 |
| com_name | str | string | 公司全称 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| email | str | string | 电子邮件 | 未单独确认；参见含义/来源定义 |  | 13/6294 |
| employees | int | double | 员工人数 | 未单独确认；参见含义/来源定义 |  | 3/6294 |
| exchange | str | string | 交易所代码 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| introduction | str | string | 公司介绍 | 未单独确认；参见含义/来源定义 |  | 5/6294 |
| main_business | str | string | 主要业务及产品 | 未单独确认；参见含义/来源定义 |  | 2/6294 |
| manager | str | string | 总经理 | 未单独确认；参见含义/来源定义 |  | 145/6294 |
| office | str | string | 办公室 | 未单独确认；参见含义/来源定义 |  | 19/6294 |
| province | str | string | 所在省份 | 未单独确认；参见含义/来源定义 |  | 0/6294 |
| reg_capital | float | double | 注册资本(万元) | 万元 |  | 0/6294 |
| secretary | str | string | 董秘 | 未单独确认；参见含义/来源定义 |  | 283/6294 |
| setup_date | str | string | 注册日期 | YYYYMMDD |  | 0/6294 |
| ts_code | str | string | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/6294 |
| website | str | string | 公司主页 | 未单独确认；参见含义/来源定义 |  | 106/6294 |

## new_share

IPO新股上市；路径 `E:\QuantData\10_canonical\new_share`；自然键 `ts_code,ipo_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 3252/3252 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 3252/3252 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 3252/3252 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/3252 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 3252/3252 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| amount | float | double | 发行总量（万股） | 万股 |  | 0/3252 |
| ballot | float | double | 中签率 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| funds | float | double | 募集资金（亿元） | 亿元 |  | 0/3252 |
| ipo_date | str | string | 上网发行日期 | YYYYMMDD | 是 | 0/3252 |
| issue_date | str | string | 上市日期 | YYYYMMDD |  | 4/3252 |
| limit_amount | float | double | 个人申购上限（万股） | 万股 |  | 0/3252 |
| market_amount | float | double | 上网发行总量（万股） | 万股 |  | 0/3252 |
| name | str | string | 名称 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| pe | float | double | 市盈率 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| price | float | double | 发行价格 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| sub_code | str | string | 申购代码 | 未单独确认；参见含义/来源定义 |  | 0/3252 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/3252 |

## bse_mapping

北交所新旧代码对照；路径 `E:\QuantData\10_canonical\bse_mapping`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 248/248 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 248/248 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/248 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/248 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 248/248 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 248/248 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/248 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/248 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 248/248 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/248 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/248 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/248 |
| list_date | str | string | 上市日期 | YYYYMMDD |  | 0/248 |
| n_code | str | string | 新代码 | 未单独确认；参见含义/来源定义 |  | 0/248 |
| name | str | string | 股票名称 | 未单独确认；参见含义/来源定义 |  | 0/248 |
| o_code | str | string | 原代码 | 未单独确认；参见含义/来源定义 |  | 0/248 |

## stock_st

ST股票列表；路径 `E:\QuantData\10_canonical\stock_st`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |
| type | str | 未观察到 | 类型 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| type_name | str | 未观察到 | 类型名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## st

ST风险警示板股票；路径 `E:\QuantData\10_canonical\st`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| imp_date | str | 未观察到 | 实施日期 | YYYYMMDD |  | 未扫描/无文件 |
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pub_date | str | 未观察到 | 发布日期 | YYYYMMDD |  | 未扫描/无文件 |
| st_explain | str | 未观察到 | st变更详细原因 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| st_reason | str | 未观察到 | st变更原因 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| st_type | str | 未观察到 | 类型 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## bak_basic

股票历史列表；路径 `E:\QuantData\10_canonical\bak_basic`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| area | str | 未观察到 | 地域 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| bvps | float | 未观察到 | 每股净资产 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| eps | float | 未观察到 | 每股收益 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| fixed_assets | float | 未观察到 | 固定资产（亿） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| float_share | float | 未观察到 | 流通股本（亿） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| gpr | float | 未观察到 | 毛利率（%） | % |  | 未扫描/无文件 |
| holder_num | int | 未观察到 | 股东人数 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| industry | str | 未观察到 | 行业 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| liquid_assets | float | 未观察到 | 流动资产（亿） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| list_date | str | 未观察到 | 上市日期 | YYYYMMDD |  | 未扫描/无文件 |
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| npr | float | 未观察到 | 净利润率（%） | % |  | 未扫描/无文件 |
| pb | float | 未观察到 | 市净率 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pe | float | 未观察到 | 市盈率（动） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| per_undp | float | 未观察到 | 每股未分配利润 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| profit_yoy | float | 未观察到 | 利润同比（%） | % |  | 未扫描/无文件 |
| reserved | float | 未观察到 | 公积金 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| reserved_pershare | float | 未观察到 | 每股公积金 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| rev_yoy | float | 未观察到 | 收入同比（%） | % |  | 未扫描/无文件 |
| total_assets | float | 未观察到 | 总资产（亿） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| total_share | float | 未观察到 | 总股本（亿） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |
| undp | float | 未观察到 | 未分配利润 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## stock_hsgt

沪深港通股票列表；路径 `E:\QuantData\10_canonical\stock_hsgt`；自然键 `ts_code,trade_date,type`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |
| type | str | 未观察到 | 类型 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |
| type_name | str | 未观察到 | 类型名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## daily

历史日线；路径 `E:\QuantData\10_canonical\daily`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 11764739/11764739 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 11764739/11764739 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/11764739 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 11764739/11764739 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| ah_amount | float | double | 盘后成交额 （千元） | 千元 |  | 11468934/11764739 |
| ah_vol | float | double | 盘后成交量 （手） | 手 |  | 11468934/11764739 |
| amount | float | double | 成交额 （千元） | 千元 |  | 0/11764739 |
| change | float | double | 涨跌额 | 未单独确认；参见含义/来源定义 |  | 224/11764739 |
| close | float | double | 收盘价 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| high | float | double | 最高价 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| low | float | double | 最低价 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| open | float | double | 开盘价 | 未单独确认；参见含义/来源定义 |  | 0/11764739 |
| pct_chg | float | double | 涨跌幅（%） 【基于除权后的昨收计算的涨跌幅：（今收-除权昨收）/除权昨收 】 | % |  | 224/11764739 |
| pre_close | float | double | 昨收价【除权价】 | 未单独确认；参见含义/来源定义 |  | 224/11764739 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/11764739 |
| ts_code | str | string | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/11764739 |
| vol | float | double | 成交量 （手） | 手 |  | 0/11764739 |

## adj_factor

复权因子；路径 `E:\QuantData\10_canonical\adj_factor`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 12277865/12277865 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 12277865/12277865 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/12277865 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 12277865/12277865 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| adj_factor | float | double | 复权因子 | 未单独确认；参见含义/来源定义 |  | 0/12277865 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/12277865 |
| ts_code | str | string | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/12277865 |

## daily_basic

每日指标；路径 `E:\QuantData\10_canonical\daily_basic`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 11674467/11674467 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 11674467/11674467 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 11674467/11674467 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/11674467 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 11674467/11674467 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/11674467 |
| circ_mv | float | double | 流通市值（万元） | 万元 |  | 90/11674467 |
| close | float | double | 当日收盘价 | 未单独确认；参见含义/来源定义 |  | 90/11674467 |
| dv_ratio | float | double | 股息率 （%），除息日发生在去年期间的派现 | % |  | 1239407/11674467 |
| dv_ttm | float | double | 股息率（TTM）（%），除息日在近12个月且分红报告期在12个月以内的派现 | % |  | 3699379/11674467 |
| float_share | float | double | 流通股本 （万股） | 万股 |  | 90/11674467 |
| free_share | float | double | 自由流通股本 （万股） | 万股 |  | 1417/11674467 |
| limit_status | int | double | 收盘涨跌状态：0-平盘，1-上涨(不含涨停)，2-涨停(不含一字涨停)，3-一字涨停，4-下跌(不含跌停)，5-跌停(不含一字跌停)，6-一字跌停 | 未单独确认；参见含义/来源定义 |  | 90/11674467 |
| pb | float | double | 市净率（总市值/(净资产-其他权益工具)） | 未单独确认；参见含义/来源定义 |  | 73609/11674467 |
| pe | float | double | 市盈率（总市值/净利润， 亏损的PE为空） | 未单独确认；参见含义/来源定义 |  | 1744232/11674467 |
| pe_ttm | float | double | 市盈率（ 总市值/净利润TTM，亏损的PE为空） | 未单独确认；参见含义/来源定义 |  | 2172095/11674467 |
| ps | float | double | 市销率 (总市值/营业收入(最新年报)) | 总市值/营业收入(最新年报 |  | 3785/11674467 |
| ps_ttm | float | double | 市销率（TTM）(总市值/营业收入TTM) | 未单独确认；参见含义/来源定义 |  | 9004/11674467 |
| total_mv | float | double | 总市值 （万元） | 万元 |  | 90/11674467 |
| total_share | float | double | 总股本 （万股） | 万股 |  | 90/11674467 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/11674467 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/11674467 |
| turnover_rate | float | double | 换手率（%） (成交量/无限售流通股数) | %; 成交量/无限售流通股数 |  | 90/11674467 |
| turnover_rate_f | float | double | 换手率（%）（自由流通股）(成交量/自由流通股数) | %; 自由流通股; 成交量/自由流通股数 |  | 455/11674467 |
| volume_ratio | float | double | 量比 VOL/MA | 未单独确认；参见含义/来源定义 |  | 17611/11674467 |

## stk_limit

每日涨跌停价格；路径 `E:\QuantData\10_canonical\stk_limit`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 12046364/12046364 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 12046364/12046364 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/12046364 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 12046364/12046364 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| asset_type | str | string | 类型 STK | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| down_limit | float | double | 跌停价 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| exchange | str | string | 交易所：SSE/SZSE/BSE | 未单独确认；参见含义/来源定义 |  | 0/12046364 |
| pre_close | float | double | 昨日收盘价 | 未单独确认；参见含义/来源定义 |  | 125671/12046364 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/12046364 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/12046364 |
| up_limit | float | double | 涨停价 | 未单独确认；参见含义/来源定义 |  | 0/12046364 |

## suspend_d

每日停复牌信息；路径 `E:\QuantData\10_canonical\suspend_d`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 334629/334629 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 334629/334629 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 334629/334629 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/334629 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 334629/334629 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| suspend_timing | str | null,string | 日内停牌时间段（日内停牌才有值，否则为空值） | 未单独确认；参见含义/来源定义 |  | 332658/334629 |
| suspend_type | str | string | 停复牌类型：S-停牌，R-复牌 | 未单独确认；参见含义/来源定义 |  | 0/334629 |
| trade_date | str | string | 停复牌日期（覆盖从停牌到覆盖期间的连续日期） | YYYYMMDD |  | 0/334629 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/334629 |

## fund_daily

ETF日线行情；路径 `E:\QuantData\10_canonical\fund_daily`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2770397/2770397 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2770397/2770397 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2770397 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2770397/2770397 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2770397 |
| amount | float | double | 成交额(千元) | 千元 |  | 0/2770397 |
| change | float | double | 涨跌额(元) | 元 |  | 0/2770397 |
| close | float | double | 收盘价(元) | 元 |  | 0/2770397 |
| high | float | double | 最高价(元) | 元 |  | 0/2770397 |
| low | float | double | 最低价(元) | 元 |  | 0/2770397 |
| open | float | double | 开盘价(元) | 元 |  | 0/2770397 |
| pct_chg | float | double | 涨跌幅(%) | % |  | 0/2770397 |
| pre_close | float | double | 昨收盘价(元) | 元 |  | 0/2770397 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/2770397 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/2770397 |
| vol | float | double | 成交量(手) | 手 |  | 0/2770397 |

## fund_nav

基金净值；路径 `E:\QuantData\10_canonical\fund_nav`；自然键 `ts_code,nav_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 3040262/3040262 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 170/3040262 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 3040262/3040262 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/3040262 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 3040262/3040262 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/3040262 |
| accum_div | float | double | 累计分红 | 未单独确认；参见含义/来源定义 |  | 3028291/3040262 |
| accum_nav | float | double | 累计净值 | 未单独确认；参见含义/来源定义 |  | 113720/3040262 |
| adj_nav | float | double | 复权单位净值 | 未单独确认；参见含义/来源定义 |  | 404/3040262 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 170/3040262 |
| nav_date | str | string | 净值日期 | YYYYMMDD | 是 | 0/3040262 |
| net_asset | float | double | 资产净值 | 未单独确认；参见含义/来源定义 |  | 2980892/3040262 |
| total_netasset | float | double | 合计资产净值 | 未单独确认；参见含义/来源定义 |  | 2989562/3040262 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/3040262 |
| unit_nav | float | double | 单位净值 | 未单独确认；参见含义/来源定义 |  | 0/3040262 |

## fund_div

基金分红；路径 `E:\QuantData\10_canonical\fund_div`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 4083/4083 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 178/4083 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 4083/4083 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 178/4083 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 4083/4083 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| account_date | str | string | 红利再投资到账日 | 未单独确认；参见含义/来源定义 |  | 3341/4083 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 178/4083 |
| base_date | str | string | 分配收益基准日 | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| base_unit | float | double | 基准基金份额(万份) | 未单独确认；参见含义/来源定义 |  | 657/4083 |
| base_year | str | string | 份额基准年度 | 未单独确认；参见含义/来源定义 |  | 186/4083 |
| div_cash | float | double | 每股派息(元) | 元 |  | 0/4083 |
| div_proc | str | string | 方案进度 | 未单独确认；参见含义/来源定义 |  | 0/4083 |
| ear_amount | float | double | 收益分配金额(元) | 元 |  | 2113/4083 |
| ear_distr | float | double | 可分配收益(元) | 元 |  | 287/4083 |
| earpay_date | str | null,string | 收益支付日 | 未单独确认；参见含义/来源定义 |  | 3897/4083 |
| ex_date | str | string | 除息日 | 未单独确认；参见含义/来源定义 |  | 186/4083 |
| imp_anndate | str | string | 分红实施公告日 | 未单独确认；参见含义/来源定义 |  | 186/4083 |
| net_ex_date | str | string | 净值除权日 | 未单独确认；参见含义/来源定义 |  | 1547/4083 |
| pay_date | str | string | 派息日 | 未单独确认；参见含义/来源定义 |  | 186/4083 |
| record_date | str | string | 权益登记日 | 未单独确认；参见含义/来源定义 |  | 186/4083 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/4083 |

## etf_limit

ETF每日涨跌停价格；路径 `E:\QuantData\10_canonical\etf_limit`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2235250/2235250 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2235250/2235250 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2235250 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2235250/2235250 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| asset_type | str | string | 类型 ETF | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| down_limit | float | double | 跌停价 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| exchange | str | string | 交易所：SSE/SZSE | 未单独确认；参见含义/来源定义 |  | 0/2235250 |
| pre_close | float | double | 昨日收盘价 | 未单独确认；参见含义/来源定义 |  | 2209367/2235250 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/2235250 |
| ts_code | str | string | 合约代码 | 未单独确认；参见含义/来源定义 | 是 | 0/2235250 |
| up_limit | float | double | 涨停价 | 未单独确认；参见含义/来源定义 |  | 0/2235250 |

## etf_basic

ETF基本信息；路径 `E:\QuantData\10_canonical\etf_basic`；自然键 `ts_code`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| cname | str | 未观察到 | 基金中文全称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| csname | str | 未观察到 | ETF中文简称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| custod_name | str | 未观察到 | 基金托管人名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| etf_type | str | 未观察到 | 基金投资通道类型（境内、QDII） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| exchange | str | 未观察到 | 交易所（上交所SH 深交所SZ） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| extname | str | 未观察到 | ETF扩位简称(对应交易所简称) | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| index_code | str | 未观察到 | ETF基准指数代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| index_name | str | 未观察到 | ETF基准指数中文全称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| list_date | str | 未观察到 | 上市日期（格式：YYYYMMDD） | YYYYMMDD |  | 未扫描/无文件 |
| list_status | str | 未观察到 | 存续状态（L上市 D退市 P待上市） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| mgr_name | str | 未观察到 | 基金管理人简称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| mgt_fee | float | 未观察到 | 基金管理人收取的费用 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| setup_date | str | 未观察到 | 设立日期（格式：YYYYMMDD） | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 基金交易代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |

## etf_index

ETF跟踪指数；路径 `E:\QuantData\10_canonical\etf_index`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| adj_circle | str | 未观察到 | 指数成份证券调整周期 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| base_date | str | 未观察到 | 指数基日 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| bp | float | 未观察到 | 指数基点(点) | 点 |  | 未扫描/无文件 |
| indx_csname | str | 未观察到 | 指数简称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| indx_name | str | 未观察到 | 指数全称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pub_date | str | 未观察到 | 指数发布日期 | YYYYMMDD |  | 未扫描/无文件 |
| pub_party_name | str | 未观察到 | 指数发布机构 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 指数代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## fund_adj

ETF复权因子；路径 `E:\QuantData\10_canonical\fund_adj`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2958557/2958557 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2958557/2958557 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2958557 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2958557/2958557 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| adj_factor | float | double | 复权因子 | 未单独确认；参见含义/来源定义 |  | 0/2958557 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/2958557 |
| ts_code | str | string | ts基金代码 | 未单独确认；参见含义/来源定义 | 是 | 0/2958557 |

## fund_portfolio

基金持仓；路径 `E:\QuantData\10_canonical\fund_portfolio`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| amount | float | 未观察到 | 持有股票数量（股） | 股 |  | 未扫描/无文件 |
| ann_date | str | 未观察到 | 公告日期 | YYYYMMDD |  | 未扫描/无文件 |
| end_date | str | 未观察到 | 截止日期 | YYYYMMDD |  | 未扫描/无文件 |
| mkv | float | 未观察到 | 持有股票市值(元) | 元 |  | 未扫描/无文件 |
| stk_float_ratio | float | 未观察到 | 占流通股本比例 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| stk_mkv_ratio | float | 未观察到 | 占股票市值比 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| symbol | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | TS基金代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## fund_share

基金规模；路径 `E:\QuantData\10_canonical\fund_share`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2058878/2058878 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2058878/2058878 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2058878/2058878 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2058878 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2058878/2058878 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| fd_share | float | double | 基金份额（万） | 未单独确认；参见含义/来源定义 |  | 0/2058878 |
| trade_date | str | string | 交易（变动）日期，格式YYYYMMDD | YYYYMMDD | 是 | 0/2058878 |
| ts_code | str | string | 基金代码，支持多只基金同时提取，用逗号分隔 | 未单独确认；参见含义/来源定义 | 是 | 0/2058878 |

## etf_share_size

ETF份额规模；路径 `E:\QuantData\10_canonical\etf_share_size`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| close | float | 未观察到 | 收盘价（元） | 元 |  | 未扫描/无文件 |
| etf_name | str | 未观察到 | 基金名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| exchange | str | 未观察到 | 交易所（SSE上交所 SZSE深交所 BSE北交所） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| nav | float | 未观察到 | 基金份额净值(元) | 元 |  | 未扫描/无文件 |
| total_share | float | 未观察到 | 总份额（万份） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| total_size | float | 未观察到 | 总规模（万元） | 万元 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | ETF代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |

## index_weight

指数成分和权重；路径 `E:\QuantData\10_canonical\index_weight`；自然键 `index_code,con_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 862089/862089 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 862089/862089 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 862089/862089 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/862089 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 862089/862089 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/862089 |
| con_code | str | string | 成分代码 | 未单独确认；参见含义/来源定义 | 是 | 0/862089 |
| index_code | str | string | 指数代码 | 未单独确认；参见含义/来源定义 | 是 | 0/862089 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/862089 |
| weight | float | double | 权重 | 未单独确认；参见含义/来源定义 |  | 0/862089 |

## index_dailybasic

大盘指数每日指标；路径 `E:\QuantData\10_canonical\index_dailybasic`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 40888/40888 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 40888/40888 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 40888/40888 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/40888 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 40888/40888 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| float_mv | float | double | 当日流通市值（元） | 元 |  | 0/40888 |
| float_share | float | double | 当日流通股本（股） | 股 |  | 0/40888 |
| free_share | float | double | 当日自由流通股本（股） | 股 |  | 0/40888 |
| pb | float | double | 市净率 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| pe | float | double | 市盈率 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| pe_ttm | float | double | 市盈率TTM（最新价除以最近4个季度的每股收益） | 最新价除以最近4个季度的每股收益 |  | 0/40888 |
| total_mv | float | double | 当日总市值（元） | 元 |  | 0/40888 |
| total_share | float | double | 当日总股本（股） | 股 |  | 0/40888 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/40888 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/40888 |
| turnover_rate | float | double | 换手率 | 未单独确认；参见含义/来源定义 |  | 0/40888 |
| turnover_rate_f | float | double | 换手率(基于自由流通股本) | 基于自由流通股本 |  | 0/40888 |

## index_member_all

申万行业成分（分级）；路径 `E:\QuantData\10_canonical\index_member_all`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 7920/7920 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 7920/7920 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 7920/7920 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/7920 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 7920/7920 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| in_date | str | string | 纳入日期 | YYYYMMDD |  | 0/7920 |
| is_new | str | string | 是否最新Y是N否 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| l1_code | str | string | 一级行业代码 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| l1_name | str | string | 一级行业名称 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| l2_code | str | string | 二级行业代码 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| l2_name | str | string | 二级行业名称 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| l3_code | str | string | 三级行业代码 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| l3_name | str | string | 三级行业名称 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| name | str | string | 成分股票名称 | 未单独确认；参见含义/来源定义 |  | 0/7920 |
| out_date | str | null,string | 剔除日期 | YYYYMMDD |  | 5914/7920 |
| ts_code | str | string | 成分股票代码 | 未单独确认；参见含义/来源定义 |  | 0/7920 |

## sw_daily

申万日线行情；路径 `E:\QuantData\10_canonical\sw_daily`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| amount | float | 未观察到 | 成交额（万元） | 万元 |  | 未扫描/无文件 |
| change | float | 未观察到 | 涨跌点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| close | float | 未观察到 | 收盘点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| float_mv | float | 未观察到 | 流通市值（万元） | 万元 |  | 未扫描/无文件 |
| high | float | 未观察到 | 最高点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| low | float | 未观察到 | 最低点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| name | str | 未观察到 | 指数名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| open | float | 未观察到 | 开盘点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pb | float | 未观察到 | 市净率 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pe | float | 未观察到 | 市盈率 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| total_mv | float | 未观察到 | 总市值（万元） | 万元 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | 指数代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |
| vol | float | 未观察到 | 成交量（万股） | 万股 |  | 未扫描/无文件 |

## ci_index_member

中信行业成分；路径 `E:\QuantData\10_canonical\ci_index_member`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| in_date | str | 未观察到 | 纳入日期 | YYYYMMDD |  | 未扫描/无文件 |
| is_new | str | 未观察到 | 是否最新Y是N否 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| l1_code | str | 未观察到 | 一级行业代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| l1_name | str | 未观察到 | 一级行业名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| l2_code | str | 未观察到 | 二级行业代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| l2_name | str | 未观察到 | 二级行业名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| l3_code | str | 未观察到 | 三级行业代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| l3_name | str | 未观察到 | 三级行业名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| name | str | 未观察到 | 成分股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| out_date | str | 未观察到 | 剔除日期 | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 成分股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## ci_daily

中信行业指数日行情；路径 `E:\QuantData\10_canonical\ci_daily`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| amount | float | 未观察到 | 成交额（万元） | 万元 |  | 未扫描/无文件 |
| change | float | 未观察到 | 涨跌点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| close | float | 未观察到 | 收盘点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| high | float | 未观察到 | 最高点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| low | float | 未观察到 | 最低点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| open | float | 未观察到 | 开盘点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pre_close | float | 未观察到 | 昨日收盘点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | 指数代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |
| vol | float | 未观察到 | 成交量（万股） | 万股 |  | 未扫描/无文件 |

## income

利润表；路径 `E:\QuantData\10_canonical\income`；自然键 `ts_code,end_date,ann_date,f_ann_date,report_type,update_flag,comp_type`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _event_available_at | 元数据 | timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/304376 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/304376 |
| adj_lossgain | float | double | 调整以前年度损益 | 未单独确认；参见含义/来源定义 |  | 304375/304376 |
| admin_exp | float | double | 减:管理费用 | 未单独确认；参见含义/来源定义 |  | 1060/304376 |
| amodcost_fin_assets | float | double | 以摊余成本计量的金融资产终止确认收益 | 未单独确认；参见含义/来源定义 |  | 294753/304376 |
| ann_date | str | string | 公告日期 | YYYYMMDD | 是 | 0/304376 |
| ass_invest_income | float | double | 其中:对联营企业和合营企业的投资收益 | 未单独确认；参见含义/来源定义 |  | 144017/304376 |
| asset_disp_income | float | double | 资产处置收益 | 未单独确认；参见含义/来源定义 |  | 112929/304376 |
| assets_impair_loss | float | double | 减:资产减值损失 | 未单独确认；参见含义/来源定义 |  | 57724/304376 |
| basic_eps | float | double | 基本每股收益 | 未单独确认；参见含义/来源定义 |  | 3389/304376 |
| biz_tax_surchg | float | double | 减:营业税金及附加 | 未单独确认；参见含义/来源定义 |  | 1830/304376 |
| capit_comstock_div | float | double | 转作股本的普通股股利 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| comm_exp | float | double | 减:手续费及佣金支出 | 未单独确认；参见含义/来源定义 |  | 295329/304376 |
| comm_income | float | double | 手续费及佣金收入 | 未单独确认；参见含义/来源定义 |  | 295656/304376 |
| comp_type | str | string | 公司类型(1一般工商业2银行3保险4证券7多元金融) | 1一般工商业2银行3保险4证券7多元金融 | 是 | 0/304376 |
| compens_payout | float | double | 赔付总支出 | 未单独确认；参见含义/来源定义 |  | 300908/304376 |
| compens_payout_refu | float | double | 减:摊回赔付支出 | 未单独确认；参见含义/来源定义 |  | 304100/304376 |
| compr_inc_attr_m_s | float | double | 归属于少数股东的综合收益总额 | 未单独确认；参见含义/来源定义 |  | 75799/304376 |
| compr_inc_attr_p | float | double | 归属于母公司(或股东)的综合收益总额 | 或股东 |  | 2502/304376 |
| comshare_payable_dvd | float | double | 应付普通股股利 | 未单独确认；参见含义/来源定义 |  | 304364/304376 |
| continued_net_profit | float | double | 持续经营净利润 | 未单独确认；参见含义/来源定义 |  | 58538/304376 |
| credit_impa_loss | float | double | 信用减值损失 | 未单独确认；参见含义/来源定义 |  | 93524/304376 |
| diluted_eps | float | double | 稀释每股收益 | 未单独确认；参见含义/来源定义 |  | 10551/304376 |
| distable_profit | float | double | 可分配利润 | 未单独确认；参见含义/来源定义 |  | 304345/304376 |
| distr_profit_shrhder | float | double | 可供股东分配的利润 | 未单独确认；参见含义/来源定义 |  | 304345/304376 |
| div_payt | float | double | 保户红利支出 | 未单独确认；参见含义/来源定义 |  | 301031/304376 |
| ebit | float | double | 息税前利润 | 未单独确认；参见含义/来源定义 |  | 34306/304376 |
| ebitda | float | double | 息税折旧摊销前利润 | 未单独确认；参见含义/来源定义 |  | 149322/304376 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 | 是 | 0/304376 |
| end_net_profit | float | double | 终止经营净利润 | 未单独确认；参见含义/来源定义 |  | 294808/304376 |
| end_type | str | string | 报告期类型 | 未单独确认；参见含义/来源定义 |  | 397/304376 |
| f_ann_date | str | string | 实际公告日期 | YYYYMMDD | 是 | 0/304376 |
| fin_exp | float | double | 减:财务费用 | 未单独确认；参见含义/来源定义 |  | 7064/304376 |
| fin_exp_int_exp | float | double | 财务费用:利息费用 | 未单独确认；参见含义/来源定义 |  | 91822/304376 |
| fin_exp_int_inc | float | double | 财务费用:利息收入 | 未单独确认；参见含义/来源定义 |  | 74306/304376 |
| forex_gain | float | double | 加:汇兑净收益 | 未单独确认；参见含义/来源定义 |  | 292915/304376 |
| fv_value_chg_gain | float | double | 加:公允价值变动净收益 | 未单独确认；参见含义/来源定义 |  | 165660/304376 |
| income_tax | float | double | 所得税费用 | 未单独确认；参见含义/来源定义 |  | 6799/304376 |
| insur_reser_refu | float | double | 减:摊回保险责任准备金 | 未单独确认；参见含义/来源定义 |  | 304099/304376 |
| insurance_exp | float | double | 保险业务支出 | 未单独确认；参见含义/来源定义 |  | 304372/304376 |
| int_exp | float | double | 减:利息支出 | 未单独确认；参见含义/来源定义 |  | 293167/304376 |
| int_income | float | double | 利息收入 | 未单独确认；参见含义/来源定义 |  | 290623/304376 |
| invest_income | float | double | 加:投资净收益 | 未单独确认；参见含义/来源定义 |  | 38208/304376 |
| minority_gain | float | double | 少数股东损益 | 未单独确认；参见含义/来源定义 |  | 74817/304376 |
| n_asset_mg_income | float | double | 受托客户资产管理业务净收入 | 未单独确认；参见含义/来源定义 |  | 301717/304376 |
| n_commis_income | float | double | 手续费及佣金净收入 | 未单独确认；参见含义/来源定义 |  | 298710/304376 |
| n_income | float | double | 净利润(含少数股东损益) | 含少数股东损益 |  | 531/304376 |
| n_income_attr_p | float | double | 净利润(不含少数股东损益) | 不含少数股东损益 |  | 28/304376 |
| n_oth_b_income | float | double | 加:其他业务净收益 | 未单独确认；参见含义/来源定义 |  | 298658/304376 |
| n_oth_income | float | double | 其他经营净收益 | 未单独确认；参见含义/来源定义 |  | 298638/304376 |
| n_sec_tb_income | float | double | 代理买卖证券业务净收入 | 未单独确认；参见含义/来源定义 |  | 301716/304376 |
| n_sec_uw_income | float | double | 证券承销业务净收入 | 未单独确认；参见含义/来源定义 |  | 301755/304376 |
| nca_disploss | float | double | 其中:减:非流动资产处置净损失 | 未单独确认；参见含义/来源定义 |  | 271404/304376 |
| net_after_nr_lp_correct | float | double | 扣除非经常性损益后的净利润（更正前） | 未单独确认；参见含义/来源定义 |  | 304185/304376 |
| net_expo_hedging_benefits | float | double | 净敞口套期收益 | 未单独确认；参见含义/来源定义 |  | 301723/304376 |
| non_oper_exp | float | double | 减:营业外支出 | 未单独确认；参见含义/来源定义 |  | 10872/304376 |
| non_oper_income | float | double | 加:营业外收入 | 未单独确认；参见含义/来源定义 |  | 10968/304376 |
| oper_cost | float | double | 减:营业成本 | 未单独确认；参见含义/来源定义 |  | 7609/304376 |
| oper_exp | float | double | 营业支出 | 未单独确认；参见含义/来源定义 |  | 298379/304376 |
| operate_profit | float | double | 营业利润 | 未单独确认；参见含义/来源定义 |  | 706/304376 |
| oth_b_income | float | double | 其他业务收入 | 未单独确认；参见含义/来源定义 |  | 298408/304376 |
| oth_compr_income | float | double | 其他综合收益 | 未单独确认；参见含义/来源定义 |  | 132980/304376 |
| oth_impair_loss_assets | float | double | 其他资产减值损失 | 未单独确认；参见含义/来源定义 |  | 302609/304376 |
| oth_income | float | double | 其他收益 | 未单独确认；参见含义/来源定义 |  | 53914/304376 |
| other_bus_cost | float | double | 其他业务成本 | 未单独确认；参见含义/来源定义 |  | 299241/304376 |
| out_prem | float | double | 减:分出保费 | 未单独确认；参见含义/来源定义 |  | 304107/304376 |
| prem_earned | float | double | 已赚保费 | 未单独确认；参见含义/来源定义 |  | 300409/304376 |
| prem_income | float | double | 保险业务收入 | 未单独确认；参见含义/来源定义 |  | 304080/304376 |
| prem_refund | float | double | 退保金 | 未单独确认；参见含义/来源定义 |  | 301589/304376 |
| prfshare_payable_dvd | float | double | 应付优先股股利 | 未单独确认；参见含义/来源定义 |  | 304375/304376 |
| rd_exp | float | double | 研发费用 | 未单独确认；参见含义/来源定义 |  | 85896/304376 |
| reins_cost_refund | float | double | 减:摊回分保费用 | 未单独确认；参见含义/来源定义 |  | 304100/304376 |
| reins_exp | float | double | 分保费用 | 未单独确认；参见含义/来源定义 |  | 302097/304376 |
| reins_income | float | double | 其中:分保费收入 | 未单独确认；参见含义/来源定义 |  | 304186/304376 |
| report_type | str | string | 报告类型 见底部表 | 未单独确认；参见含义/来源定义 | 是 | 0/304376 |
| reser_insur_liab | float | double | 提取保险责任准备金 | 未单独确认；参见含义/来源定义 |  | 300533/304376 |
| revenue | float | double | 营业收入 | 未单独确认；参见含义/来源定义 |  | 487/304376 |
| sell_exp | float | double | 减:销售费用 | 未单独确认；参见含义/来源定义 |  | 12661/304376 |
| t_compr_income | float | double | 综合收益总额 | 未单独确认；参见含义/来源定义 |  | 2489/304376 |
| total_cogs | float | double | 营业总成本 | 未单独确认；参见含义/来源定义 |  | 998/304376 |
| total_opcost | float | double | 营业总成本（二） | 未单独确认；参见含义/来源定义 |  | 8037/304376 |
| total_profit | float | double | 利润总额 | 未单独确认；参见含义/来源定义 |  | 491/304376 |
| total_revenue | float | double | 营业总收入 | 未单独确认；参见含义/来源定义 |  | 429/304376 |
| transfer_housing_imprest | float | double | 住房周转金转入 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| transfer_oth | float | double | 其他转入 | 未单独确认；参见含义/来源定义 |  | 304375/304376 |
| transfer_surplus_rese | float | double | 盈余公积转入 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/304376 |
| undist_profit | float | double | 年初未分配利润 | 未单独确认；参见含义/来源定义 |  | 304345/304376 |
| une_prem_reser | float | double | 提取未到期责任准备金 | 未单独确认；参见含义/来源定义 |  | 304107/304376 |
| update_flag | str | string | 更新标识 | 未单独确认；参见含义/来源定义 | 是 | 0/304376 |
| withdra_biz_devfund | float | double | 提取企业发展基金 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| withdra_legal_pubfund | float | double | 提取法定公益金 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| withdra_legal_surplus | float | double | 提取法定盈余公积 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| withdra_oth_ersu | float | double | 提取任意盈余公积金 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| withdra_rese_fund | float | double | 提取储备基金 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |
| workers_welfare | float | double | 职工奖金福利 | 未单独确认；参见含义/来源定义 |  | 304376/304376 |

## balancesheet

资产负债表；路径 `E:\QuantData\10_canonical\balancesheet`；自然键 `ts_code,end_date,ann_date,f_ann_date,report_type,update_flag,comp_type`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _event_available_at | 元数据 | timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 317069/317069 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/317069 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/317069 |
| acc_exp | float | double | 预提费用 | 未单独确认；参见含义/来源定义 |  | 317054/317069 |
| acc_receivable | float | double | 应收款项 | 未单独确认；参见含义/来源定义 |  | 314212/317069 |
| accounts_pay | float | double | 应付票据及应付账款 | 未单独确认；参见含义/来源定义 |  | 10191/317069 |
| accounts_receiv | float | double | 应收账款 | 未单独确认；参见含义/来源定义 |  | 9927/317069 |
| accounts_receiv_bill | float | double | 应收票据及应收账款 | 未单独确认；参见含义/来源定义 |  | 11152/317069 |
| acct_payable | float | double | 应付账款 | 未单独确认；参见含义/来源定义 |  | 21843/317069 |
| acting_trading_sec | float | double | 代理买卖证券款 | 未单独确认；参见含义/来源定义 |  | 310160/317069 |
| acting_uw_sec | float | double | 代理承销证券款 | 未单独确认；参见含义/来源定义 |  | 312836/317069 |
| adv_receipts | float | double | 预收款项 | 未单独确认；参见含义/来源定义 |  | 132527/317069 |
| agency_bus_liab | float | double | 代理业务负债 | 未单独确认；参见含义/来源定义 |  | 317069/317069 |
| amor_exp | float | double | 待摊费用 | 未单独确认；参见含义/来源定义 |  | 317067/317069 |
| ann_date | str | string | 公告日期 | YYYYMMDD | 是 | 0/317069 |
| bond_payable | float | double | 应付债券 | 未单独确认；参见含义/来源定义 |  | 261612/317069 |
| cap_rese | float | double | 资本公积金 | 未单独确认；参见含义/来源定义 |  | 3120/317069 |
| cash_reser_cb | float | double | 现金及存放中央银行款项 | 未单独确认；参见含义/来源定义 |  | 313581/317069 |
| cb_borr | float | double | 向中央银行借款 | 未单独确认；参见含义/来源定义 |  | 310523/317069 |
| cip | float | double | 在建工程 | 未单独确认；参见含义/来源定义 |  | 82301/317069 |
| cip_total | float | double | 在建工程(合计)(元) | 元 |  | 54174/317069 |
| client_depos | float | double | 其中：客户资金存款 | 未单独确认；参见含义/来源定义 |  | 314335/317069 |
| client_prov | float | double | 其中：客户备付金 | 未单独确认；参见含义/来源定义 |  | 314327/317069 |
| comm_payable | float | double | 应付手续费及佣金 | 未单独确认；参见含义/来源定义 |  | 312878/317069 |
| comp_type | str | string | 公司类型(1一般工商业2银行3保险4证券7多元金融) | 1一般工商业2银行3保险4证券7多元金融 | 是 | 0/317069 |
| const_materials | float | double | 工程物资 | 未单独确认；参见含义/来源定义 |  | 279058/317069 |
| contract_assets | float | double | 合同资产 | 未单独确认；参见含义/来源定义 |  | 251519/317069 |
| contract_liab | float | double | 合同负债 | 未单独确认；参见含义/来源定义 |  | 138250/317069 |
| cost_fin_assets | float | double | 以摊余成本计量的金融资产 | 未单独确认；参见含义/来源定义 |  | 316463/317069 |
| debt_invest | float | double | 债权投资(元) | 元 |  | 301316/317069 |
| decr_in_disbur | float | double | 发放贷款及垫款 | 未单独确认；参见含义/来源定义 |  | 305846/317069 |
| defer_inc_non_cur_liab | float | double | 递延收益-非流动负债 | 未单独确认；参见含义/来源定义 |  | 61182/317069 |
| defer_tax_assets | float | double | 递延所得税资产 | 未单独确认；参见含义/来源定义 |  | 12030/317069 |
| defer_tax_liab | float | double | 递延所得税负债 | 未单独确认；参见含义/来源定义 |  | 105935/317069 |
| deferred_inc | float | double | 递延收益 | 未单独确认；参见含义/来源定义 |  | 316910/317069 |
| depos | float | double | 吸收存款 | 未单独确认；参见含义/来源定义 |  | 314062/317069 |
| depos_ib_deposits | float | double | 吸收存款及同业存放 | 未单独确认；参见含义/来源定义 |  | 311610/317069 |
| depos_in_oth_bfi | float | double | 存放同业和其它金融机构款项 | 未单独确认；参见含义/来源定义 |  | 314106/317069 |
| depos_oth_bfi | float | double | 同业和其它金融机构存放款项 | 未单独确认；参见含义/来源定义 |  | 314176/317069 |
| depos_received | float | double | 存入保证金 | 未单独确认；参见含义/来源定义 |  | 317069/317069 |
| deriv_assets | float | double | 衍生金融资产 | 未单独确认；参见含义/来源定义 |  | 296993/317069 |
| deriv_liab | float | double | 衍生金融负债 | 未单独确认；参见含义/来源定义 |  | 297363/317069 |
| div_payable | float | double | 应付股利 | 未单独确认；参见含义/来源定义 |  | 216605/317069 |
| div_receiv | float | double | 应收股利 | 未单独确认；参见含义/来源定义 |  | 277702/317069 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 | 是 | 0/317069 |
| end_type | str | string | 报告期类型 | 未单独确认；参见含义/来源定义 |  | 719/317069 |
| estimated_liab | float | double | 预计负债 | 未单独确认；参见含义/来源定义 |  | 210258/317069 |
| f_ann_date | str | string | 实际公告日期 | YYYYMMDD | 是 | 0/317069 |
| fa_avail_for_sale | float | double | 可供出售金融资产 | 未单独确认；参见含义/来源定义 |  | 254881/317069 |
| fair_value_fin_assets | float | double | 以公允价值计量且其变动计入其他综合收益的金融资产 | 未单独确认；参见含义/来源定义 |  | 316474/317069 |
| fix_assets | float | double | 固定资产 | 未单独确认；参见含义/来源定义 |  | 30997/317069 |
| fix_assets_total | float | double | 固定资产(合计)(元) | 元 |  | 9601/317069 |
| fixed_assets_disp | float | double | 固定资产清理 | 未单独确认；参见含义/来源定义 |  | 285565/317069 |
| forex_differ | float | double | 外币报表折算差额 | 未单独确认；参见含义/来源定义 |  | 316882/317069 |
| goodwill | float | double | 商誉 | 未单独确认；参见含义/来源定义 |  | 165873/317069 |
| hfs_assets | float | double | 持有待售的资产 | 未单独确认；参见含义/来源定义 |  | 302180/317069 |
| hfs_sales | float | double | 持有待售的负债 | 未单独确认；参见含义/来源定义 |  | 311062/317069 |
| htm_invest | float | double | 持有至到期投资 | 未单独确认；参见含义/来源定义 |  | 312433/317069 |
| indem_payable | float | double | 应付赔付款 | 未单独确认；参见含义/来源定义 |  | 316780/317069 |
| indep_acct_assets | float | double | 独立账户资产 | 未单独确认；参见含义/来源定义 |  | 316895/317069 |
| indept_acc_liab | float | double | 独立账户负债 | 未单独确认；参见含义/来源定义 |  | 316894/317069 |
| int_payable | float | double | 应付利息 | 未单独确认；参见含义/来源定义 |  | 196678/317069 |
| int_receiv | float | double | 应收利息 | 未单独确认；参见含义/来源定义 |  | 253877/317069 |
| intan_assets | float | double | 无形资产 | 未单独确认；参见含义/来源定义 |  | 4954/317069 |
| inventories | float | double | 存货 | 未单独确认；参见含义/来源定义 |  | 12862/317069 |
| invest_as_receiv | float | double | 应收款项类投资 | 未单独确认；参见含义/来源定义 |  | 316203/317069 |
| invest_loss_unconf | float | double | 未确认的投资损失 | 未单独确认；参见含义/来源定义 |  | 317064/317069 |
| invest_real_estate | float | double | 投资性房地产 | 未单独确认；参见含义/来源定义 |  | 172632/317069 |
| lease_liab | float | double | 租赁负债 | 未单独确认；参见含义/来源定义 |  | 188587/317069 |
| lending_funds | float | double | 融出资金 | 未单独确认；参见含义/来源定义 |  | 314277/317069 |
| loan_oth_bank | float | double | 拆入资金 | 未单独确认；参见含义/来源定义 |  | 307179/317069 |
| loanto_oth_bank_fi | float | double | 拆出资金 | 未单独确认；参见含义/来源定义 |  | 310018/317069 |
| long_pay_total | float | double | 长期应付款(合计)(元) | 元 |  | 211410/317069 |
| lt_amor_exp | float | double | 长期待摊费用 | 未单独确认；参见含义/来源定义 |  | 52912/317069 |
| lt_borr | float | double | 长期借款 | 未单独确认；参见含义/来源定义 |  | 150180/317069 |
| lt_eqt_invest | float | double | 长期股权投资 | 未单独确认；参见含义/来源定义 |  | 118587/317069 |
| lt_payable | float | double | 长期应付款 | 未单独确认；参见含义/来源定义 |  | 257240/317069 |
| lt_payroll_payable | float | double | 长期应付职工薪酬 | 未单独确认；参见含义/来源定义 |  | 279121/317069 |
| lt_rec | float | double | 长期应收款 | 未单独确认；参见含义/来源定义 |  | 254319/317069 |
| minority_int | float | double | 少数股东权益 | 未单独确认；参见含义/来源定义 |  | 77570/317069 |
| money_cap | float | double | 货币资金 | 未单独确认；参见含义/来源定义 |  | 4323/317069 |
| nca_within_1y | float | double | 一年内到期的非流动资产 | 未单独确认；参见含义/来源定义 |  | 259283/317069 |
| non_cur_liab_due_1y | float | double | 一年内到期的非流动负债 | 未单独确认；参见含义/来源定义 |  | 104082/317069 |
| notes_payable | float | double | 应付票据 | 未单独确认；参见含义/来源定义 |  | 122321/317069 |
| notes_receiv | float | double | 应收票据 | 未单独确认；参见含义/来源定义 |  | 90805/317069 |
| oil_and_gas_assets | float | double | 油气资产 | 未单独确认；参见含义/来源定义 |  | 311474/317069 |
| ordin_risk_reser | float | double | 一般风险准备 | 未单独确认；参见含义/来源定义 |  | 300738/317069 |
| oth_assets | float | double | 其他资产 | 未单独确认；参见含义/来源定义 |  | 310682/317069 |
| oth_comp_income | float | double | 其他综合收益 | 未单独确认；参见含义/来源定义 |  | 121488/317069 |
| oth_cur_assets | float | double | 其他流动资产 | 未单独确认；参见含义/来源定义 |  | 20726/317069 |
| oth_cur_liab | float | double | 其他流动负债 | 未单独确认；参见含义/来源定义 |  | 117921/317069 |
| oth_debt_invest | float | double | 其他债权投资(元) | 元 |  | 307141/317069 |
| oth_eq_invest | float | double | 其他权益工具投资(元) | 元 |  | 218163/317069 |
| oth_eq_ppbond | float | double | 其他权益工具:永续债(元) | 元 |  | 307670/317069 |
| oth_eqt_tools | float | double | 其他权益工具 | 未单独确认；参见含义/来源定义 |  | 288561/317069 |
| oth_eqt_tools_p_shr | float | double | 其他权益工具(优先股) | 优先股 |  | 311269/317069 |
| oth_illiq_fin_assets | float | double | 其他非流动金融资产(元) | 元 |  | 249933/317069 |
| oth_liab | float | double | 其他负债 | 未单独确认；参见含义/来源定义 |  | 310780/317069 |
| oth_nca | float | double | 其他非流动资产 | 未单独确认；参见含义/来源定义 |  | 71428/317069 |
| oth_ncl | float | double | 其他非流动负债 | 未单独确认；参见含义/来源定义 |  | 270851/317069 |
| oth_pay_total | float | double | 其他应付款(合计)(元) | 元 |  | 9858/317069 |
| oth_payable | float | double | 其他应付款 | 未单独确认；参见含义/来源定义 |  | 98930/317069 |
| oth_rcv_total | float | double | 其他应收款(合计)（元） | 元 |  | 9786/317069 |
| oth_receiv | float | double | 其他应收款 | 未单独确认；参见含义/来源定义 |  | 105682/317069 |
| payable_to_reinsurer | float | double | 应付分保账款 | 未单独确认；参见含义/来源定义 |  | 313170/317069 |
| payables | float | double | 应付款项 | 未单独确认；参见含义/来源定义 |  | 314281/317069 |
| payroll_payable | float | double | 应付职工薪酬 | 未单独确认；参见含义/来源定义 |  | 2532/317069 |
| ph_invest | float | double | 保户储金及投资款 | 未单独确认；参见含义/来源定义 |  | 316788/317069 |
| ph_pledge_loans | float | double | 保户质押贷款 | 未单独确认；参见含义/来源定义 |  | 316870/317069 |
| pledge_borr | float | double | 其中:质押借款 | 未单独确认；参见含义/来源定义 |  | 317069/317069 |
| policy_div_payable | float | double | 应付保单红利 | 未单独确认；参见含义/来源定义 |  | 316838/317069 |
| prec_metals | float | double | 贵金属 | 未单独确认；参见含义/来源定义 |  | 315799/317069 |
| prem_receiv_adva | float | double | 预收保费 | 未单独确认；参见含义/来源定义 |  | 316676/317069 |
| premium_receiv | float | double | 应收保费 | 未单独确认；参见含义/来源定义 |  | 312996/317069 |
| prepayment | float | double | 预付款项 | 未单独确认；参见含义/来源定义 |  | 9121/317069 |
| produc_bio_assets | float | double | 生产性生物资产 | 未单独确认；参见含义/来源定义 |  | 302913/317069 |
| pur_resale_fa | float | double | 买入返售金融资产 | 未单独确认；参见含义/来源定义 |  | 306075/317069 |
| r_and_d | float | double | 研发支出 | 未单独确认；参见含义/来源定义 |  | 256486/317069 |
| receiv_financing | float | double | 应收款项融资 | 未单独确认；参见含义/来源定义 |  | 194098/317069 |
| refund_cap_depos | float | double | 存出资本保证金 | 未单独确认；参见含义/来源定义 |  | 316680/317069 |
| refund_depos | float | double | 存出保证金 | 未单独确认；参见含义/来源定义 |  | 314296/317069 |
| reinsur_receiv | float | double | 应收分保账款 | 未单独确认；参见含义/来源定义 |  | 313047/317069 |
| reinsur_res_receiv | float | double | 应收分保合同准备金 | 未单独确认；参见含义/来源定义 |  | 313406/317069 |
| report_type | str | string | 报表类型 | 未单独确认；参见含义/来源定义 | 是 | 0/317069 |
| reser_lins_liab | float | double | 寿险责任准备金 | 未单独确认；参见含义/来源定义 |  | 316854/317069 |
| reser_lthins_liab | float | double | 长期健康险责任准备金 | 未单独确认；参见含义/来源定义 |  | 316854/317069 |
| reser_outstd_claims | float | double | 未决赔款准备金 | 未单独确认；参见含义/来源定义 |  | 316829/317069 |
| reser_une_prem | float | double | 未到期责任准备金 | 未单独确认；参见含义/来源定义 |  | 316829/317069 |
| rr_reins_lins_liab | float | double | 应收分保寿险责任准备金 | 未单独确认；参见含义/来源定义 |  | 316863/317069 |
| rr_reins_lthins_liab | float | double | 应收分保长期健康险责任准备金 | 未单独确认；参见含义/来源定义 |  | 316859/317069 |
| rr_reins_outstd_cla | float | double | 应收分保未决赔款准备金 | 未单独确认；参见含义/来源定义 |  | 316834/317069 |
| rr_reins_une_prem | float | double | 应收分保未到期责任准备金 | 未单独确认；参见含义/来源定义 |  | 316834/317069 |
| rsrv_insur_cont | float | double | 保险合同准备金 | 未单独确认；参见含义/来源定义 |  | 313639/317069 |
| sett_rsrv | float | double | 结算备付金 | 未单独确认；参见含义/来源定义 |  | 309644/317069 |
| sold_for_repur_fa | float | double | 卖出回购金融资产款 | 未单独确认；参见含义/来源定义 |  | 306249/317069 |
| special_rese | float | double | 专项储备 | 未单独确认；参见含义/来源定义 |  | 235885/317069 |
| specific_payables | float | double | 专项应付款 | 未单独确认；参见含义/来源定义 |  | 276389/317069 |
| st_bonds_payable | float | double | 应付短期债券 | 未单独确认；参见含义/来源定义 |  | 316505/317069 |
| st_borr | float | double | 短期借款 | 未单独确认；参见含义/来源定义 |  | 77585/317069 |
| st_fin_payable | float | double | 应付短期融资款 | 未单独确认；参见含义/来源定义 |  | 314486/317069 |
| surplus_rese | float | double | 盈余公积金 | 未单独确认；参见含义/来源定义 |  | 5990/317069 |
| taxes_payable | float | double | 应交税费 | 未单独确认；参见含义/来源定义 |  | 1170/317069 |
| time_deposits | float | double | 定期存款 | 未单独确认；参见含义/来源定义 |  | 316688/317069 |
| total_assets | float | double | 资产总计 | 未单独确认；参见含义/来源定义 |  | 35/317069 |
| total_cur_assets | float | double | 流动资产合计 | 未单独确认；参见含义/来源定义 |  | 7257/317069 |
| total_cur_liab | float | double | 流动负债合计 | 未单独确认；参见含义/来源定义 |  | 7227/317069 |
| total_hldr_eqy_exc_min_int | float | double | 股东权益合计(不含少数股东权益) | 不含少数股东权益 |  | 98/317069 |
| total_hldr_eqy_inc_min_int | float | double | 股东权益合计(含少数股东权益) | 含少数股东权益 |  | 522/317069 |
| total_liab | float | double | 负债合计 | 未单独确认；参见含义/来源定义 |  | 233/317069 |
| total_liab_hldr_eqy | float | double | 负债及股东权益总计 | 未单独确认；参见含义/来源定义 |  | 342/317069 |
| total_nca | float | double | 非流动资产合计 | 未单独确认；参见含义/来源定义 |  | 7404/317069 |
| total_ncl | float | double | 非流动负债合计 | 未单独确认；参见含义/来源定义 |  | 16316/317069 |
| total_share | float | double | 期末总股本（股） | 股 |  | 1437/317069 |
| trad_asset | float | double | 交易性金融资产 | 未单独确认；参见含义/来源定义 |  | 175843/317069 |
| trading_fl | float | double | 交易性金融负债 | 未单独确认；参见含义/来源定义 |  | 285850/317069 |
| transac_seat_fee | float | double | 其中:交易席位费 | 未单独确认；参见含义/来源定义 |  | 317033/317069 |
| treasury_share | float | double | 减:库存股 | 未单独确认；参见含义/来源定义 |  | 232362/317069 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/317069 |
| undistr_porfit | float | double | 未分配利润 | 未单独确认；参见含义/来源定义 |  | 1054/317069 |
| update_flag | str | string | 更新标识 | 未单独确认；参见含义/来源定义 | 是 | 0/317069 |
| use_right_assets | float | double | 使用权资产 | 未单独确认；参见含义/来源定义 |  | 181341/317069 |

## cashflow

现金流量表；路径 `E:\QuantData\10_canonical\cashflow`；自然键 `ts_code,end_date,ann_date,f_ann_date,report_type,update_flag,comp_type`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 315608/315608 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/315608 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/315608 |
| amort_intang_assets | float | double | 无形资产摊销 | 未单独确认；参见含义/来源定义 |  | 144609/315608 |
| ann_date | str | string | 公告日期 | YYYYMMDD | 是 | 0/315608 |
| beg_bal_cash | float | double | 减:现金的期初余额 | 未单独确认；参见含义/来源定义 |  | 144190/315608 |
| beg_bal_cash_equ | float | double | 减:现金等价物的期初余额 | 未单独确认；参见含义/来源定义 |  | 309731/315608 |
| c_cash_equ_beg_period | float | double | 期初现金及现金等价物余额 | 未单独确认；参见含义/来源定义 |  | 451/315608 |
| c_cash_equ_end_period | float | double | 期末现金及现金等价物余额 | 未单独确认；参见含义/来源定义 |  | 402/315608 |
| c_disp_withdrwl_invest | float | double | 收回投资收到的现金 | 未单独确认；参见含义/来源定义 |  | 130560/315608 |
| c_fr_oth_operate_a | float | double | 收到其他与经营活动有关的现金 | 未单独确认；参见含义/来源定义 |  | 616/315608 |
| c_fr_sale_sg | float | double | 销售商品、提供劳务收到的现金 | 未单独确认；参见含义/来源定义 |  | 6525/315608 |
| c_inf_fr_operate_a | float | double | 经营活动现金流入小计 | 未单独确认；参见含义/来源定义 |  | 413/315608 |
| c_paid_for_taxes | float | double | 支付的各项税费 | 未单独确认；参见含义/来源定义 |  | 702/315608 |
| c_paid_goods_s | float | double | 购买商品、接受劳务支付的现金 | 未单独确认；参见含义/来源定义 |  | 6830/315608 |
| c_paid_invest | float | double | 投资支付的现金 | 未单独确认；参见含义/来源定义 |  | 109123/315608 |
| c_paid_to_for_empl | float | double | 支付给职工以及为职工支付的现金 | 未单独确认；参见含义/来源定义 |  | 508/315608 |
| c_pay_acq_const_fiolta | float | double | 购建固定资产、无形资产和其他长期资产支付的现金 | 未单独确认；参见含义/来源定义 |  | 2981/315608 |
| c_pay_claims_orig_inco | float | double | 支付原保险合同赔付款项的现金 | 未单独确认；参见含义/来源定义 |  | 311723/315608 |
| c_pay_dist_dpcp_int_exp | float | double | 分配股利、利润或偿付利息支付的现金 | 未单独确认；参见含义/来源定义 |  | 24802/315608 |
| c_prepay_amt_borr | float | double | 偿还债务支付的现金 | 未单独确认；参见含义/来源定义 |  | 67452/315608 |
| c_recp_borrow | float | double | 取得借款收到的现金 | 未单独确认；参见含义/来源定义 |  | 77478/315608 |
| c_recp_cap_contrib | float | double | 吸收投资收到的现金 | 未单独确认；参见含义/来源定义 |  | 192430/315608 |
| c_recp_return_invest | float | double | 取得投资收益收到的现金 | 未单独确认；参见含义/来源定义 |  | 100010/315608 |
| comp_type | str | string | 公司类型(1一般工商业2银行3保险4证券7多元金融) | 1一般工商业2银行3保险4证券7多元金融 | 是 | 0/315608 |
| conv_copbonds_due_within_1y | float | double | 一年内到期的可转换公司债券 | 未单独确认；参见含义/来源定义 |  | 314901/315608 |
| conv_debt_into_cap | float | double | 债务转为资本 | 未单独确认；参见含义/来源定义 |  | 314481/315608 |
| credit_impa_loss | float | double | 信用减值损失 | 未单独确认；参见含义/来源定义 |  | 250363/315608 |
| decr_def_inc_tax_assets | float | double | 递延所得税资产减少 | 未单独确认；参见含义/来源定义 |  | 150825/315608 |
| decr_deferred_exp | float | double | 待摊费用减少 | 未单独确认；参见含义/来源定义 |  | 315522/315608 |
| decr_inventories | float | double | 存货的减少 | 未单独确认；参见含义/来源定义 |  | 147584/315608 |
| decr_oper_payable | float | double | 经营性应收项目的减少 | 未单独确认；参见含义/来源定义 |  | 141658/315608 |
| depr_fa_coga_dpba | float | double | 固定资产折旧、油气资产折耗、生产性生物资产折旧 | 未单独确认；参见含义/来源定义 |  | 142330/315608 |
| eff_fx_flu_cash | float | double | 汇率变动对现金的影响 | 未单独确认；参见含义/来源定义 |  | 77934/315608 |
| end_bal_cash | float | double | 现金的期末余额 | 未单独确认；参见含义/来源定义 |  | 144157/315608 |
| end_bal_cash_equ | float | double | 加:现金等价物的期末余额 | 未单独确认；参见含义/来源定义 |  | 309805/315608 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 | 是 | 0/315608 |
| end_type | str | string | 报告期类型 | 未单独确认；参见含义/来源定义 |  | 117/315608 |
| f_ann_date | str | string | 实际公告日期 | YYYYMMDD | 是 | 0/315608 |
| fa_fnc_leases | float | double | 融资租入固定资产 | 未单独确认；参见含义/来源定义 |  | 313910/315608 |
| finan_exp | float | double | 财务费用 | 未单独确认；参见含义/来源定义 |  | 150802/315608 |
| free_cashflow | float | double | 企业自由现金流量 | 未单独确认；参见含义/来源定义 |  | 47219/315608 |
| ifc_cash_incr | float | double | 收取利息和手续费净增加额 | 未单独确认；参见含义/来源定义 |  | 299985/315608 |
| im_n_incr_cash_equ | float | double | 现金及现金等价物净增加额(间接法) | 未单独确认；参见含义/来源定义 |  | 144100/315608 |
| im_net_cashflow_oper_act | float | double | 经营活动产生的现金流量净额(间接法) | 未单独确认；参见含义/来源定义 |  | 141518/315608 |
| incl_cash_rec_saims | float | double | 其中:子公司吸收少数股东投资收到的现金 | 未单独确认；参见含义/来源定义 |  | 248619/315608 |
| incl_dvd_profit_paid_sc_ms | float | double | 其中:子公司支付给少数股东的股利、利润 | 未单独确认；参见含义/来源定义 |  | 255546/315608 |
| incr_acc_exp | float | double | 预提费用增加 | 未单独确认；参见含义/来源定义 |  | 315580/315608 |
| incr_def_inc_tax_liab | float | double | 递延所得税负债增加 | 未单独确认；参见含义/来源定义 |  | 201848/315608 |
| incr_oper_payable | float | double | 经营性应付项目的增加 | 未单独确认；参见含义/来源定义 |  | 141638/315608 |
| invest_loss | float | double | 投资损失 | 未单独确认；参见含义/来源定义 |  | 162773/315608 |
| loss_disp_fiolta | float | double | 处置固定、无形资产和其他长期资产的损失 | 未单独确认；参见含义/来源定义 |  | 173201/315608 |
| loss_fv_chg | float | double | 公允价值变动损失 | 未单独确认；参见含义/来源定义 |  | 230730/315608 |
| loss_scr_fa | float | double | 固定资产报废损失 | 未单独确认；参见含义/来源定义 |  | 210464/315608 |
| lt_amort_deferred_exp | float | double | 长期待摊费用摊销 | 未单独确认；参见含义/来源定义 |  | 166866/315608 |
| n_cap_incr_repur | float | double | 回购业务资金净增加额 | 未单独确认；参见含义/来源定义 |  | 309351/315608 |
| n_cash_flows_fnc_act | float | double | 筹资活动产生的现金流量净额 | 未单独确认；参见含义/来源定义 |  | 8157/315608 |
| n_cashflow_act | float | double | 经营活动产生的现金流量净额 | 未单独确认；参见含义/来源定义 |  | 55/315608 |
| n_cashflow_inv_act | float | double | 投资活动产生的现金流量净额 | 未单独确认；参见含义/来源定义 |  | 1284/315608 |
| n_depos_incr_fi | float | double | 客户存款和同业存放款项净增加额 | 未单独确认；参见含义/来源定义 |  | 308074/315608 |
| n_disp_subs_oth_biz | float | double | 取得子公司及其他营业单位支付的现金净额 | 未单独确认；参见含义/来源定义 |  | 270027/315608 |
| n_inc_borr_oth_fi | float | double | 向其他金融机构拆入资金净增加额 | 未单独确认；参见含义/来源定义 |  | 311564/315608 |
| n_incr_cash_cash_equ | float | double | 现金及现金等价物净增加额 | 未单独确认；参见含义/来源定义 |  | 228/315608 |
| n_incr_clt_loan_adv | float | double | 客户贷款及垫款净增加额 | 未单独确认；参见含义/来源定义 |  | 304171/315608 |
| n_incr_dep_cbob | float | double | 存放央行和同业款项净增加额 | 未单独确认；参见含义/来源定义 |  | 309198/315608 |
| n_incr_disp_faas | float | double | 处置可供出售金融资产净增加额 | 未单独确认；参见含义/来源定义 |  | 315570/315608 |
| n_incr_disp_tfa | float | double | 处置交易性金融资产净增加额 | 未单独确认；参见含义/来源定义 |  | 314439/315608 |
| n_incr_insured_dep | float | double | 保户储金净增加额 | 未单独确认；参见含义/来源定义 |  | 311928/315608 |
| n_incr_loans_cb | float | double | 向中央银行借款净增加额 | 未单独确认；参见含义/来源定义 |  | 310336/315608 |
| n_incr_loans_oth_bank | float | double | 拆入资金净增加额 | 未单独确认；参见含义/来源定义 |  | 308644/315608 |
| n_incr_pledge_loan | float | double | 质押贷款净增加额 | 未单独确认；参见含义/来源定义 |  | 311383/315608 |
| n_recp_disp_fiolta | float | double | 处置固定资产、无形资产和其他长期资产收回的现金净额 | 未单独确认；参见含义/来源定义 |  | 72495/315608 |
| n_recp_disp_sobu | float | double | 处置子公司及其他营业单位收到的现金净额 | 未单独确认；参见含义/来源定义 |  | 274248/315608 |
| n_reinsur_prem | float | double | 收到再保业务现金净额 | 未单独确认；参见含义/来源定义 |  | 312069/315608 |
| net_cash_rece_sec | float | double | 代理买卖证券收到的现金净额(元) | 元 |  | 310988/315608 |
| net_dism_capital_add | float | double | 拆出资金净增加额 | 未单独确认；参见含义/来源定义 |  | 312667/315608 |
| net_profit | float | double | 净利润 | 未单独确认；参见含义/来源定义 |  | 141516/315608 |
| oth_cash_pay_oper_act | float | double | 支付其他与经营活动有关的现金 | 未单独确认；参见含义/来源定义 |  | 454/315608 |
| oth_cash_recp_ral_fnc_act | float | double | 收到其他与筹资活动有关的现金 | 未单独确认；参见含义/来源定义 |  | 185337/315608 |
| oth_cashpay_ral_fnc_act | float | double | 支付其他与筹资活动有关的现金 | 未单独确认；参见含义/来源定义 |  | 76450/315608 |
| oth_loss_asset | float | double | 其他资产减值损失 | 未单独确认；参见含义/来源定义 |  | 315404/315608 |
| oth_pay_ral_inv_act | float | double | 支付其他与投资活动有关的现金 | 未单独确认；参见含义/来源定义 |  | 198521/315608 |
| oth_recp_ral_inv_act | float | double | 收到其他与投资活动有关的现金 | 未单独确认；参见含义/来源定义 |  | 188636/315608 |
| others | float | double | 其他 | 未单独确认；参见含义/来源定义 |  | 305386/315608 |
| pay_comm_insur_plcy | float | double | 支付保单红利的现金 | 未单独确认；参见含义/来源定义 |  | 311844/315608 |
| pay_handling_chrg | float | double | 支付手续费的现金 | 未单独确认；参见含义/来源定义 |  | 302491/315608 |
| prem_fr_orig_contr | float | double | 收到原保险合同保费取得的现金 | 未单独确认；参见含义/来源定义 |  | 311620/315608 |
| proc_issue_bonds | float | double | 发行债券收到的现金 | 未单独确认；参见含义/来源定义 |  | 303145/315608 |
| prov_depr_assets | float | double | 加:资产减值准备 | 未单独确认；参见含义/来源定义 |  | 154819/315608 |
| recp_tax_rends | float | double | 收到的税费返还 | 未单独确认；参见含义/来源定义 |  | 80709/315608 |
| report_type | str | string | 报表类型 | 未单独确认；参见含义/来源定义 | 是 | 0/315608 |
| st_cash_out_act | float | double | 经营活动现金流出小计 | 未单独确认；参见含义/来源定义 |  | 418/315608 |
| stot_cash_in_fnc_act | float | double | 筹资活动现金流入小计 | 未单独确认；参见含义/来源定义 |  | 43923/315608 |
| stot_cashout_fnc_act | float | double | 筹资活动现金流出小计 | 未单独确认；参见含义/来源定义 |  | 10669/315608 |
| stot_inflows_inv_act | float | double | 投资活动现金流入小计 | 未单独确认；参见含义/来源定义 |  | 20803/315608 |
| stot_out_inv_act | float | double | 投资活动现金流出小计 | 未单独确认；参见含义/来源定义 |  | 2088/315608 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/315608 |
| uncon_invest_loss | float | double | 未确认投资损失 | 未单独确认；参见含义/来源定义 |  | 315607/315608 |
| update_flag | str | string | 更新标志(1最新） | 未单独确认；参见含义/来源定义 | 是 | 0/315608 |
| use_right_asset_dep | float | double | 使用权资产折旧 | 未单独确认；参见含义/来源定义 |  | 239758/315608 |

## fina_indicator

财务指标数据；路径 `E:\QuantData\10_canonical\fina_indicator`；自然键 `ts_code,end_date,ann_date,update_flag`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 389530/389530 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 389530/389530 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/389530 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/389530 |
| adminexp_of_gr | float | double | 管理费用/营业总收入 | 未单独确认；参见含义/来源定义 |  | 2125/389530 |
| ann_date | str | string | 公告日期 | YYYYMMDD | 是 | 0/389530 |
| ar_turn | float | double | 应收账款周转率 | 未单独确认；参见含义/来源定义 |  | 21628/389530 |
| arturn_days | float | double | 应收账款周转天数 | 未单独确认；参见含义/来源定义 |  | 21667/389530 |
| assets_to_eqt | float | double | 权益乘数 | 未单独确认；参见含义/来源定义 |  | 16718/389530 |
| assets_turn | float | double | 总资产周转率 | 未单独确认；参见含义/来源定义 |  | 10310/389530 |
| assets_yoy | float | double | 资产总计相对年初增长率(%) | % |  | 13842/389530 |
| basic_eps_yoy | float | double | 基本每股收益同比增长率(%) | % |  | 24966/389530 |
| bps | float | double | 每股净资产 | 未单独确认；参见含义/来源定义 |  | 13063/389530 |
| bps_yoy | float | double | 每股净资产相对年初增长率(%) | % |  | 15576/389530 |
| ca_to_assets | float | double | 流动资产/总资产 | 未单独确认；参见含义/来源定义 |  | 20227/389530 |
| ca_turn | float | double | 流动资产周转率 | 未单独确认；参见含义/来源定义 |  | 18661/389530 |
| capital_rese_ps | float | double | 每股资本公积 | 未单独确认；参见含义/来源定义 |  | 15043/389530 |
| capitalized_to_da | float | double | 资本支出/折旧和摊销 | 未单独确认；参见含义/来源定义 |  | 186638/389530 |
| cash_ratio | float | double | 保守速动比率 | 未单独确认；参见含义/来源定义 |  | 20511/389530 |
| cash_to_liqdebt | float | double | 货币资金／流动负债 | 未单独确认；参见含义/来源定义 |  | 20541/389530 |
| cash_to_liqdebt_withinterest | float | double | 货币资金／带息流动负债 | 未单独确认；参见含义/来源定义 |  | 65741/389530 |
| cfps | float | double | 每股现金流量净额 | 未单独确认；参见含义/来源定义 |  | 13185/389530 |
| cfps_yoy | float | double | 每股经营活动产生的现金流量净额同比增长率(%) | % |  | 33692/389530 |
| cogs_of_sales | float | double | 销售成本率 | 未单独确认；参见含义/来源定义 |  | 10027/389530 |
| current_exint | float | double | 无息流动负债 | 未单独确认；参见含义/来源定义 |  | 20487/389530 |
| current_ratio | float | double | 流动比率 | 未单独确认；参见含义/来源定义 |  | 18464/389530 |
| currentdebt_to_debt | float | double | 流动负债/负债合计 | 未单独确认；参见含义/来源定义 |  | 20217/389530 |
| daa | float | double | 折旧与摊销 | 未单独确认；参见含义/来源定义 |  | 185224/389530 |
| debt_to_assets | float | double | 资产负债率 | 未单独确认；参见含义/来源定义 |  | 12064/389530 |
| debt_to_eqt | float | double | 产权比率 | 未单独确认；参见含义/来源定义 |  | 17096/389530 |
| diluted2_eps | float | double | 期末摊薄每股收益 | 未单独确认；参见含义/来源定义 |  | 13025/389530 |
| dp_assets_to_eqt | float | double | 权益乘数(杜邦分析) | 未单独确认；参见含义/来源定义 |  | 18997/389530 |
| dt_eps | float | double | 稀释每股收益 | 未单独确认；参见含义/来源定义 |  | 23877/389530 |
| dt_eps_yoy | float | double | 稀释每股收益同比增长率(%) | % |  | 34113/389530 |
| dt_netprofit_yoy | float | double | 归属母公司股东的净利润-扣除非经常损益同比增长率(%) | % |  | 24392/389530 |
| dtprofit_to_profit | float | double | 扣除非经常损益后的净利润/净利润 | 未单独确认；参见含义/来源定义 |  | 73837/389530 |
| ebit | float | double | 息税前利润 | 未单独确认；参见含义/来源定义 |  | 8489/389530 |
| ebit_of_gr | float | double | 息税前利润/营业总收入 | 未单独确认；参见含义/来源定义 |  | 9302/389530 |
| ebit_ps | float | double | 每股息税前利润 | 未单独确认；参见含义/来源定义 |  | 20468/389530 |
| ebit_to_interest | float | double | 已获利息倍数(EBIT/利息费用) | 未单独确认；参见含义/来源定义 |  | 135337/389530 |
| ebitda | float | double | 息税折旧摊销前利润 | 未单独确认；参见含义/来源定义 |  | 188836/389530 |
| ebitda_to_debt | float | double | 息税折旧摊销前利润/负债合计 | 未单独确认；参见含义/来源定义 |  | 191560/389530 |
| ebt_yoy | float | double | 利润总额同比增长率(%) | % |  | 19753/389530 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 | 是 | 0/389530 |
| eps | float | double | 基本每股收益 | 未单独确认；参见含义/来源定义 |  | 14937/389530 |
| eqt_to_debt | float | double | 归属于母公司的股东权益/负债合计 | 未单独确认；参见含义/来源定义 |  | 12145/389530 |
| eqt_to_interestdebt | float | double | 归属于母公司的股东权益/带息债务 | 未单独确认；参见含义/来源定义 |  | 59045/389530 |
| eqt_to_talcapital | float | double | 归属于母公司的股东权益/全部投入资本 | 未单独确认；参见含义/来源定义 |  | 22148/389530 |
| eqt_yoy | float | double | 归属母公司的股东权益相对年初增长率(%) | % |  | 14000/389530 |
| equity_yoy | float | double | 净资产同比增长率 | 未单独确认；参见含义/来源定义 |  | 33473/389530 |
| expense_of_sales | float | double | 销售期间费用率 | 未单独确认；参见含义/来源定义 |  | 9631/389530 |
| extra_item | float | double | 非经常性损益 | 未单独确认；参见含义/来源定义 |  | 12445/389530 |
| fa_turn | float | double | 固定资产周转率 | 未单独确认；参见含义/来源定义 |  | 8932/389530 |
| fcfe | float | double | 股权自由现金流量 | 未单独确认；参见含义/来源定义 |  | 30853/389530 |
| fcfe_ps | float | double | 每股股东自由现金流量 | 未单独确认；参见含义/来源定义 |  | 32331/389530 |
| fcff | float | double | 企业自由现金流量 | 未单独确认；参见含义/来源定义 |  | 29407/389530 |
| fcff_ps | float | double | 每股企业自由现金流量 | 未单独确认；参见含义/来源定义 |  | 32331/389530 |
| finaexp_of_gr | float | double | 财务费用/营业总收入 | 未单独确认；参见含义/来源定义 |  | 9805/389530 |
| fixed_assets | float | double | 固定资产合计 | 未单独确认；参见含义/来源定义 |  | 13454/389530 |
| gc_of_gr | float | double | 营业总成本/营业总收入 | 未单独确认；参见含义/来源定义 |  | 9535/389530 |
| gross_margin | float | double | 毛利 | 未单独确认；参见含义/来源定义 |  | 9251/389530 |
| grossprofit_margin | float | double | 销售毛利率 | 未单独确认；参见含义/来源定义 |  | 10019/389530 |
| impai_ttm | float | double | 资产减值损失/营业总收入 | 未单独确认；参见含义/来源定义 |  | 72394/389530 |
| int_to_talcap | float | double | 带息债务/全部投入资本 | 未单独确认；参见含义/来源定义 |  | 22119/389530 |
| interestdebt | float | double | 带息债务 | 未单独确认；参见含义/来源定义 |  | 19519/389530 |
| interst_income | float | double | 利息费用 | 未单独确认；参见含义/来源定义 |  | 75368/389530 |
| inv_turn | float | double | 存货周转率 | 未单独确认；参见含义/来源定义 |  | 27302/389530 |
| invest_capital | float | double | 全部投入资本 | 未单独确认；参见含义/来源定义 |  | 19319/389530 |
| investincome_of_ebt | float | double | 价值变动净收益/利润总额 | 未单独确认；参见含义/来源定义 |  | 102561/389530 |
| invturn_days | float | double | 存货周转天数 | 未单独确认；参见含义/来源定义 |  | 27321/389530 |
| longdeb_to_debt | float | double | 非流动负债/负债合计 | 未单独确认；参见含义/来源定义 |  | 30500/389530 |
| longdebt_to_workingcapital | float | double | 长期债务与营运资金比率 | 未单独确认；参见含义/来源定义 |  | 86899/389530 |
| n_op_profit_of_ebt | float | double | 营业外收支净额/利润总额 | 未单独确认；参见含义/来源定义 |  | 68138/389530 |
| nca_to_assets | float | double | 非流动资产/总资产 | 未单独确认；参见含义/来源定义 |  | 20352/389530 |
| netdebt | float | double | 净债务 | 未单独确认；参见含义/来源定义 |  | 19519/389530 |
| netprofit_margin | float | double | 销售净利率 | 未单独确认；参见含义/来源定义 |  | 1723/389530 |
| netprofit_yoy | float | double | 归属母公司股东的净利润同比增长率(%) | % |  | 19210/389530 |
| networking_capital | float | double | 营运流动资本 | 未单独确认；参见含义/来源定义 |  | 20487/389530 |
| non_op_profit | float | double | 非营业利润 | 未单独确认；参见含义/来源定义 |  | 858/389530 |
| noncurrent_exint | float | double | 无息非流动负债 | 未单独确认；参见含义/来源定义 |  | 30440/389530 |
| nop_to_ebt | float | double | 非营业利润／利润总额 | 未单独确认；参见含义/来源定义 |  | 65554/389530 |
| npta | float | double | 总资产净利润 | 未单独确认；参见含义/来源定义 |  | 965/389530 |
| ocf_to_debt | float | double | 经营活动产生的现金流量净额/负债合计 | 未单独确认；参见含义/来源定义 |  | 12405/389530 |
| ocf_to_interestdebt | float | double | 经营活动产生的现金流量净额/带息债务 | 未单独确认；参见含义/来源定义 |  | 59238/389530 |
| ocf_to_netdebt | float | double | 经营活动产生的现金流量净额/净债务 | 未单独确认；参见含义/来源定义 |  | 214321/389530 |
| ocf_to_opincome | float | double | 经营活动产生的现金流量净额/经营活动净收益 | 未单独确认；参见含义/来源定义 |  | 93285/389530 |
| ocf_to_or | float | double | 经营活动产生的现金流量净额/营业收入 | 未单独确认；参见含义/来源定义 |  | 1897/389530 |
| ocf_to_profit | float | double | 经营活动产生的现金流量净额／营业利润 | 未单独确认；参见含义/来源定义 |  | 69483/389530 |
| ocf_to_shortdebt | float | double | 经营活动产生的现金流量净额/流动负债 | 未单独确认；参见含义/来源定义 |  | 20373/389530 |
| ocf_yoy | float | double | 经营活动产生的现金流量净额同比增长率(%) | % |  | 20127/389530 |
| ocfps | float | double | 每股经营活动产生的现金流量净额 | 未单独确认；参见含义/来源定义 |  | 12265/389530 |
| op_income | float | double | 经营活动净收益 | 未单独确认；参见含义/来源定义 |  | 725/389530 |
| op_of_gr | float | double | 营业利润/营业总收入 | 未单独确认；参见含义/来源定义 |  | 1711/389530 |
| op_to_debt | float | double | 营业利润／负债合计 | 未单独确认；参见含义/来源定义 |  | 12222/389530 |
| op_to_ebt | float | double | 营业利润／利润总额 | 未单独确认；参见含义/来源定义 |  | 65586/389530 |
| op_to_liqdebt | float | double | 营业利润／流动负债 | 未单独确认；参见含义/来源定义 |  | 20240/389530 |
| op_yoy | float | double | 营业利润同比增长率(%) | % |  | 19893/389530 |
| opincome_of_ebt | float | double | 经营活动净收益/利润总额 | 未单独确认；参见含义/来源定义 |  | 65697/389530 |
| or_yoy | float | double | 营业收入同比增长率(%) | % |  | 20139/389530 |
| profit_dedt | float | double | 扣除非经常性损益后的净利润（扣非净利润） | 未单独确认；参见含义/来源定义 |  | 12449/389530 |
| profit_prefin_exp | float | double | 扣除财务费用前营业利润 | 未单独确认；参见含义/来源定义 |  | 8530/389530 |
| profit_to_gr | float | double | 净利润/营业总收入 | 未单独确认；参见含义/来源定义 |  | 1676/389530 |
| profit_to_op | float | double | 利润总额／营业收入 | 未单独确认；参见含义/来源定义 |  | 1678/389530 |
| q_adminexp_to_gr | float | double | 管理费用／营业总收入 (单季度) | 未单独确认；参见含义/来源定义 |  | 26709/389530 |
| q_dt_roe | float | double | 净资产单季度收益率(扣除非经常损益) | 未单独确认；参见含义/来源定义 |  | 46487/389530 |
| q_dtprofit | float | double | 扣除非经常损益后的单季度净利润 | 未单独确认；参见含义/来源定义 |  | 42706/389530 |
| q_dtprofit_to_profit | float | double | 扣除非经常损益后的净利润／净利润(单季度) | 未单独确认；参见含义/来源定义 |  | 113658/389530 |
| q_eps | float | double | 每股收益(单季度) | 未单独确认；参见含义/来源定义 |  | 35673/389530 |
| q_exp_to_sales | float | double | 销售期间费用率(单季度) | 未单独确认；参见含义/来源定义 |  | 33763/389530 |
| q_finaexp_to_gr | float | double | 财务费用／营业总收入 (单季度) | 未单独确认；参见含义/来源定义 |  | 33908/389530 |
| q_gc_to_gr | float | double | 营业总成本／营业总收入 (单季度) | 未单独确认；参见含义/来源定义 |  | 33684/389530 |
| q_gr_qoq | float | double | 营业总收入环比增长率(%)(单季度) | % |  | 30672/389530 |
| q_gr_yoy | float | double | 营业总收入同比增长率(%)(单季度) | % |  | 48097/389530 |
| q_gsprofit_margin | float | double | 销售毛利率(单季度) | 未单独确认；参见含义/来源定义 |  | 33514/389530 |
| q_impair_to_gr_ttm | float | double | 资产减值损失／营业总收入(单季度) | 未单独确认；参见含义/来源定义 |  | 97771/389530 |
| q_investincome | float | double | 价值变动单季度净收益 | 未单独确认；参见含义/来源定义 |  | 66821/389530 |
| q_investincome_to_ebt | float | double | 价值变动净收益／利润总额(单季度) | 未单独确认；参见含义/来源定义 |  | 130824/389530 |
| q_netprofit_margin | float | double | 销售净利率(单季度) | 未单独确认；参见含义/来源定义 |  | 26267/389530 |
| q_netprofit_qoq | float | double | 归属母公司股东的净利润环比增长率(%)(单季度) | % |  | 29864/389530 |
| q_netprofit_yoy | float | double | 归属母公司股东的净利润同比增长率(%)(单季度) | % |  | 47268/389530 |
| q_npta | float | double | 总资产净利润(单季度) | 未单独确认；参见含义/来源定义 |  | 26636/389530 |
| q_ocf_to_or | float | double | 经营活动产生的现金流量净额／经营活动净收益(单季度) | 未单独确认；参见含义/来源定义 |  | 125140/389530 |
| q_ocf_to_sales | float | double | 经营活动产生的现金流量净额／营业收入(单季度) | 未单独确认；参见含义/来源定义 |  | 26901/389530 |
| q_op_qoq | float | double | 营业利润环比增长率(%)(单季度) | % |  | 29935/389530 |
| q_op_to_gr | float | double | 营业利润／营业总收入(单季度) | 未单独确认；参见含义/来源定义 |  | 26247/389530 |
| q_op_yoy | float | double | 营业利润同比增长率(%)(单季度) | % |  | 47317/389530 |
| q_opincome | float | double | 经营活动单季度净收益 | 未单独确认；参见含义/来源定义 |  | 24962/389530 |
| q_opincome_to_ebt | float | double | 经营活动净收益／利润总额(单季度) | 未单独确认；参见含义/来源定义 |  | 98523/389530 |
| q_profit_qoq | float | double | 净利润环比增长率(%)(单季度) | % |  | 29882/389530 |
| q_profit_to_gr | float | double | 净利润／营业总收入(单季度) | 未单独确认；参见含义/来源定义 |  | 26207/389530 |
| q_profit_yoy | float | double | 净利润同比增长率(%)(单季度) | % |  | 47282/389530 |
| q_roe | float | double | 净资产收益率(单季度) | 未单独确认；参见含义/来源定义 |  | 30585/389530 |
| q_saleexp_to_gr | float | double | 销售费用／营业总收入 (单季度) | 未单独确认；参见含义/来源定义 |  | 40242/389530 |
| q_sales_qoq | float | double | 营业收入环比增长率(%)(单季度) | % |  | 30721/389530 |
| q_sales_yoy | float | double | 营业收入同比增长率(%)(单季度) | % |  | 48037/389530 |
| q_salescash_to_or | float | double | 销售商品提供劳务收到的现金／营业收入(单季度) | 未单独确认；参见含义/来源定义 |  | 34599/389530 |
| quick_ratio | float | double | 速动比率 | 未单独确认；参见含义/来源定义 |  | 18822/389530 |
| rd_exp | float | double | 研发投入合计 | 未单独确认；参见含义/来源定义 |  | 123185/389530 |
| retained_earnings | float | double | 留存收益 | 未单独确认；参见含义/来源定义 |  | 13069/389530 |
| retainedps | float | double | 每股留存收益 | 未单独确认；参见含义/来源定义 |  | 13081/389530 |
| revenue_ps | float | double | 每股营业收入 | 未单独确认；参见含义/来源定义 |  | 13618/389530 |
| roa | float | double | 总资产报酬率 | 未单独确认；参见含义/来源定义 |  | 8601/389530 |
| roa2_yearly | float | double | 年化总资产报酬率 | 未单独确认；参见含义/来源定义 |  | 8606/389530 |
| roa_dp | float | double | 总资产净利率(杜邦分析) | 未单独确认；参见含义/来源定义 |  | 14279/389530 |
| roa_yearly | float | double | 年化总资产净利率 | 未单独确认；参见含义/来源定义 |  | 966/389530 |
| roe | float | double | 净资产收益率 | 未单独确认；参见含义/来源定义 |  | 5461/389530 |
| roe_avg | float | double | 平均净资产收益率(增发条件) | 未单独确认；参见含义/来源定义 |  | 180248/389530 |
| roe_dt | float | double | 净资产收益率(扣除非经常损益) | 未单独确认；参见含义/来源定义 |  | 16937/389530 |
| roe_waa | float | double | 加权平均净资产收益率 | 未单独确认；参见含义/来源定义 |  | 20201/389530 |
| roe_yearly | float | double | 年化净资产收益率 | 未单独确认；参见含义/来源定义 |  | 5470/389530 |
| roe_yoy | float | double | 净资产收益率(摊薄)同比增长率(%) | % |  | 39554/389530 |
| roic | float | double | 投入资本回报率 | 未单独确认；参见含义/来源定义 |  | 10980/389530 |
| roic_yearly | float | double | 年化投入资本回报率 | 未单独确认；参见含义/来源定义 |  | 10984/389530 |
| saleexp_to_gr | float | double | 销售费用/营业总收入 | 未单独确认；参见含义/来源定义 |  | 16780/389530 |
| salescash_to_or | float | double | 销售商品提供劳务收到的现金/营业收入 | 未单独确认；参见含义/来源定义 |  | 10203/389530 |
| surplus_rese_ps | float | double | 每股盈余公积 | 未单独确认；参见含义/来源定义 |  | 19226/389530 |
| tangasset_to_intdebt | float | double | 有形资产/带息债务 | 未单独确认；参见含义/来源定义 |  | 59045/389530 |
| tangible_asset | float | double | 有形资产 | 未单独确认；参见含义/来源定义 |  | 19306/389530 |
| tangibleasset_to_debt | float | double | 有形资产/负债合计 | 未单独确认；参见含义/来源定义 |  | 19512/389530 |
| tangibleasset_to_netdebt | float | double | 有形资产/净债务 | 未单独确认；参见含义/来源定义 |  | 214150/389530 |
| tax_to_ebt | float | double | 所得税/利润总额 | 未单独确认；参见含义/来源定义 |  | 69062/389530 |
| tbassets_to_totalassets | float | double | 有形资产/总资产 | 未单独确认；参见含义/来源定义 |  | 19327/389530 |
| total_fa_trun | float | double | 固定资产合计周转率 | 未单独确认；参见含义/来源定义 |  | 11578/389530 |
| total_revenue_ps | float | double | 每股营业总收入 | 未单独确认；参见含义/来源定义 |  | 13572/389530 |
| tr_yoy | float | double | 营业总收入同比增长率(%) | % |  | 20072/389530 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/389530 |
| turn_days | float | double | 营业周期 | 未单独确认；参见含义/来源定义 |  | 19552/389530 |
| undist_profit_ps | float | double | 每股未分配利润 | 未单独确认；参见含义/来源定义 |  | 13096/389530 |
| update_flag | str | string | 更新标识 | 未单独确认；参见含义/来源定义 | 是 | 0/389530 |
| valuechange_income | float | double | 价值变动净收益 | 未单独确认；参见含义/来源定义 |  | 47528/389530 |
| working_capital | float | double | 营运资金 | 未单独确认；参见含义/来源定义 |  | 20203/389530 |

## forecast

业绩预告；路径 `E:\QuantData\10_canonical\forecast`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 83958/83958 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 83958/83958 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/83958 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/83958 |
| change_reason | str | string | 业绩变动原因 | 未单独确认；参见含义/来源定义 |  | 19186/83958 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| first_ann_date | str | string | 首次公告日 | 未单独确认；参见含义/来源定义 |  | 60/83958 |
| last_parent_net | float | double | 上年同期归属母公司净利润 | 未单独确认；参见含义/来源定义 |  | 3205/83958 |
| net_profit_max | float | double | 预告净利润上限（万元） | 万元 |  | 6267/83958 |
| net_profit_min | float | double | 预告净利润下限（万元） | 万元 |  | 6235/83958 |
| p_change_max | float | double | 预告净利润变动幅度上限（%） | % |  | 4698/83958 |
| p_change_min | float | double | 预告净利润变动幅度下限（%） | % |  | 4619/83958 |
| summary | str | string | 业绩预告摘要 | 未单独确认；参见含义/来源定义 |  | 59/83958 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/83958 |
| type | str | string | 业绩预告类型(预增/预减/扭亏/首亏/续亏/续盈/略增/略减) | 未单独确认；参见含义/来源定义 |  | 0/83958 |

## express

业绩快报；路径 `E:\QuantData\10_canonical\express`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 20609/20609 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 20609/20609 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/20609 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/20609 |
| bps | float | double | 每股净资产 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| diluted_eps | float | double | 每股收益(摊薄)(元) | 元 |  | 89/20609 |
| diluted_roe | float | double | 净资产收益率(摊薄)(%) | % |  | 192/20609 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| eps_last_year | float | double | 去年同期每股收益 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| growth_assets | float | double | 比年初增长率:总资产 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| growth_bps | float | double | 比年初增长率:归属于母公司股东的每股净资产 | 未单独确认；参见含义/来源定义 |  | 20550/20609 |
| is_audit | int | double | 是否审计： 1是 0否 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| n_income | float | double | 净利润(元) | 元 |  | 65/20609 |
| np_last_year | float | double | 去年同期净利润 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| op_last_year | float | double | 去年同期营业利润 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| open_bps | float | double | 期初每股净资产 | 未单独确认；参见含义/来源定义 |  | 20550/20609 |
| open_net_assets | float | double | 期初净资产 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| operate_profit | float | double | 营业利润(元) | 元 |  | 1225/20609 |
| or_last_year | float | double | 去年同期营业收入 | 未单独确认；参见含义/来源定义 |  | 20605/20609 |
| perf_summary | str | null,string | 业绩简要说明 | 未单独确认；参见含义/来源定义 |  | 20609/20609 |
| remark | str | null,string | 备注 | 未单独确认；参见含义/来源定义 |  | 20609/20609 |
| revenue | float | double | 营业收入(元) | 元 |  | 10/20609 |
| total_assets | float | double | 总资产(元) | 元 |  | 82/20609 |
| total_hldr_eqy_exc_min_int | float | double | 股东权益合计(不含少数股东权益)(元) | 不含少数股东权益; 元 |  | 96/20609 |
| total_profit | float | double | 利润总额(元) | 元 |  | 663/20609 |
| tp_last_year | float | double | 去年同期利润总额 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/20609 |
| yoy_dedu_np | float | double | 同比增长率:归属母公司股东的净利润 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| yoy_eps | float | double | 同比增长率:基本每股收益 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| yoy_equity | float | double | 比年初增长率:归属母公司的股东权益 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| yoy_net_profit | float | double | 去年同期修正后净利润 | 未单独确认；参见含义/来源定义 |  | 66/20609 |
| yoy_op | float | double | 同比增长率:营业利润 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| yoy_roe | float | double | 同比增减:加权平均净资产收益率 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |
| yoy_sales | float | double | 同比增长率:营业收入 | 未单独确认；参见含义/来源定义 |  | 20605/20609 |
| yoy_tp | float | double | 同比增长率:利润总额 | 未单独确认；参见含义/来源定义 |  | 20547/20609 |

## dividend

分红送股数据；路径 `E:\QuantData\10_canonical\dividend`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 212937/212937 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 437/212937 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 212937/212937 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 394/212937 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 43/212937 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 43/212937 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| ann_date | str | null,string | 公告日(预案，决案) | 未单独确认；参见含义/来源定义 |  | 394/212937 |
| base_date | str | string | 基准日 | 未单独确认；参见含义/来源定义 |  | 113718/212937 |
| base_share | float | double | 基准股本（万） | 未单独确认；参见含义/来源定义 |  | 112356/212937 |
| cash_div | float | double | 每股分红（税后） | 未单独确认；参见含义/来源定义 |  | 64245/212937 |
| cash_div_tax | float | double | 每股分红（税前） | 未单独确认；参见含义/来源定义 |  | 62912/212937 |
| div_listdate | str | string | 红股上市日 | 未单独确认；参见含义/来源定义 |  | 206490/212937 |
| div_proc | str | string | 实施进度 | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| end_date | str | string | 分红年度 | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| ex_date | str | string | 除权除息日 | 未单独确认；参见含义/来源定义 |  | 171551/212937 |
| imp_ann_date | str | string | 实施公告日 | 未单独确认；参见含义/来源定义 |  | 171609/212937 |
| pay_date | str | string | 派息日 | 未单独确认；参见含义/来源定义 |  | 172356/212937 |
| record_date | str | string | 股权登记日 | 未单独确认；参见含义/来源定义 |  | 171473/212937 |
| stk_bo_rate | float | double | 每股送股比例 | 未单独确认；参见含义/来源定义 |  | 211902/212937 |
| stk_co_rate | float | double | 每股转增比例 | 未单独确认；参见含义/来源定义 |  | 200120/212937 |
| stk_div | float | double | 每股送转 | 未单独确认；参见含义/来源定义 |  | 0/212937 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/212937 |

## disclosure_date

财报披露日期表；路径 `E:\QuantData\10_canonical\disclosure_date`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 300176/300176 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 300176/300176 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 2504/300176 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| actual_date | str | null,string | 实际披露日期 | YYYYMMDD |  | 2504/300176 |
| ann_date | str | string | 最新披露公告日 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/300176 |
| modify_date | str | null,string | 披露日期修正记录 | YYYYMMDD |  | 285721/300176 |
| pre_date | str | string | 预计披露日期 | YYYYMMDD |  | 0/300176 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/300176 |

## fina_audit

财务审计意见；路径 `E:\QuantData\10_canonical\fina_audit`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 63516/63516 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 63516/63516 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/63516 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/63516 |
| audit_agency | str | string | 会计事务所 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| audit_fees | float | double | 审计总费用（元） | 元 |  | 21528/63516 |
| audit_result | str | string | 审计结果 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| audit_sign | str | string | 签字会计师 | 未单独确认；参见含义/来源定义 |  | 251/63516 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/63516 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/63516 |

## fina_mainbz

主营业务构成；路径 `E:\QuantData\10_canonical\fina_mainbz`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1780812/1780812 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1780812/1780812 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 1780812/1780812 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/1780812 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| bz_code | str | string | 主营业务来源类型（P-按产品 D-按地区 I-按行业） | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| bz_cost | float | double | 主营业务成本(元) | 元 |  | 449748/1780812 |
| bz_item | str | string | 主营业务来源 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| bz_profit | float | double | 主营业务利润(元) | 元 |  | 491360/1780812 |
| bz_sales | float | double | 主营业务收入(元) | 元 |  | 44127/1780812 |
| curr_type | str | string | 货币代码（CNY） | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |
| update_flag | str | string | 是否更新 | 未单独确认；参见含义/来源定义 |  | 0/1780812 |

## moneyflow

个股资金流向；路径 `E:\QuantData\10_canonical\moneyflow`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 11421685/11421685 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 11421685/11421685 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 11421685/11421685 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/11421685 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 11421685/11421685 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/11421685 |
| buy_elg_amount | float | double | 特大单买入金额（万元） | 万元 |  | 0/11421685 |
| buy_elg_vol | int | double | 特大单买入量（手） | 手 |  | 0/11421685 |
| buy_lg_amount | float | double | 大单买入金额（万元） | 万元 |  | 0/11421685 |
| buy_lg_vol | int | double | 大单买入量（手） | 手 |  | 0/11421685 |
| buy_md_amount | float | double | 中单买入金额（万元） | 万元 |  | 0/11421685 |
| buy_md_vol | int | double | 中单买入量（手） | 手 |  | 0/11421685 |
| buy_sm_amount | float | double | 小单买入金额（万元） | 万元 |  | 0/11421685 |
| buy_sm_vol | int | double | 小单买入量（手） | 手 |  | 0/11421685 |
| net_mf_amount | float | double | 净流入额（万元） | 万元 |  | 0/11421685 |
| net_mf_vol | int | double | 净流入量（手） | 手 |  | 0/11421685 |
| sell_elg_amount | float | double | 特大单卖出金额（万元） | 万元 |  | 0/11421685 |
| sell_elg_vol | int | double | 特大单卖出量（手） | 手 |  | 0/11421685 |
| sell_lg_amount | float | double | 大单卖出金额（万元） | 万元 |  | 0/11421685 |
| sell_lg_vol | int | double | 大单卖出量（手） | 手 |  | 0/11421685 |
| sell_md_amount | float | double | 中单卖出金额（万元） | 万元 |  | 0/11421685 |
| sell_md_vol | int | double | 中单卖出量（手） | 手 |  | 0/11421685 |
| sell_sm_amount | float | double | 小单卖出金额（万元） | 万元 |  | 0/11421685 |
| sell_sm_vol | int | double | 小单卖出量（手） | 手 |  | 0/11421685 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/11421685 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/11421685 |

## margin

融资融券交易汇总；路径 `E:\QuantData\10_canonical\margin`；自然键 `trade_date,exchange_id`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6579/6579 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6579/6579 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 6579/6579 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/6579 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 6579/6579 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/6579 |
| exchange_id | str | string | 交易所代码（SSE上交所SZSE深交所BSE北交所） | 未单独确认；参见含义/来源定义 | 是 | 0/6579 |
| rqmcl | float | double | 融券卖出量(股,份,手) | 股,份,手 |  | 0/6579 |
| rqye | float | double | 融券余额(元) | 元 |  | 0/6579 |
| rqyl | float | double | 融券余量(股,份,手) | 股,份,手 |  | 2286/6579 |
| rzche | float | double | 融资偿还额(元) | 元 |  | 0/6579 |
| rzmre | float | double | 融资买入额(元) | 元 |  | 0/6579 |
| rzrqye | float | double | 融资融券余额(元) | 元 |  | 0/6579 |
| rzye | float | double | 融资余额(元) | 元 |  | 0/6579 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/6579 |

## margin_detail

融资融券交易明细；路径 `E:\QuantData\10_canonical\margin_detail`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6436851/6436851 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6436851/6436851 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 6436851/6436851 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/6436851 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 6436851/6436851 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/6436851 |
| name | str | null,string | 股票名称 （20190910后有数据） | 未单独确认；参见含义/来源定义 |  | 1098226/6436851 |
| rqchl | float | double | 融券偿还量(股) | 股 |  | 39/6436851 |
| rqmcl | float | double | 融券卖出量(股,份,手) | 股,份,手 |  | 33/6436851 |
| rqye | float | double | 融券余额(元) | 元 |  | 3220/6436851 |
| rqyl | float | double | 融券余量（股） | 股 |  | 33/6436851 |
| rzche | float | double | 融资偿还额(元) | 元 |  | 38/6436851 |
| rzmre | float | double | 融资买入额(元) | 元 |  | 33/6436851 |
| rzrqye | float | double | 融资融券余额(元) | 元 |  | 3220/6436851 |
| rzye | float | double | 融资余额(元) | 元 |  | 33/6436851 |
| trade_date | str | string | 交易日期 | YYYYMMDD | 是 | 0/6436851 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 | 是 | 0/6436851 |

## margin_secs

融资融券标的（盘前）；路径 `E:\QuantData\10_canonical\margin_secs`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 7858001/7858001 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 7858001/7858001 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 7858001/7858001 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/7858001 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 7858001/7858001 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| exchange | str | string | 交易所 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| name | str | string | 标的名称 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |
| trade_date | str | string | 交易日期 | YYYYMMDD |  | 0/7858001 |
| ts_code | str | string | 标的代码 | 未单独确认；参见含义/来源定义 |  | 0/7858001 |

## hsgt_top10

沪深股通十大成交股；路径 `E:\QuantData\10_canonical\hsgt_top10`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 50010/50010 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 50010/50010 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 50010/50010 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/50010 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 50010/50010 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| amount | float | double | 成交金额（元） | 元 |  | 0/50010 |
| buy | float | double | 买入金额（元） | 元 |  | 9801/50010 |
| change | float | double | 涨跌额 | 未单独确认；参见含义/来源定义 |  | 82/50010 |
| close | float | double | 收盘价 | 未单独确认；参见含义/来源定义 |  | 80/50010 |
| market_type | str | string | 市场类型（1：沪市 3：深市） | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| name | str | string | 股票名称 | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| net_amount | float | double | 净成交金额（元） | 元 |  | 9800/50010 |
| rank | int | double | 资金排名 | 未单独确认；参见含义/来源定义 |  | 0/50010 |
| sell | float | double | 卖出金额（元） | 元 |  | 9800/50010 |
| trade_date | str | string | 交易日期 | YYYYMMDD |  | 0/50010 |
| ts_code | str | string | 股票代码 | 未单独确认；参见含义/来源定义 |  | 0/50010 |

## moneyflow_ths

个股资金流向（THS）；路径 `E:\QuantData\10_canonical\moneyflow_ths`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| buy_lg_amount | float | 未观察到 | 今日大单净流入额(万元) | 万元 |  | 未扫描/无文件 |
| buy_lg_amount_rate | float | 未观察到 | 今日大单净流入占比(%) | % |  | 未扫描/无文件 |
| buy_md_amount | float | 未观察到 | 今日中单净流入额(万元) | 万元 |  | 未扫描/无文件 |
| buy_md_amount_rate | float | 未观察到 | 今日中单净流入占比(%) | % |  | 未扫描/无文件 |
| buy_sm_amount | float | 未观察到 | 今日小单净流入额(万元) | 万元 |  | 未扫描/无文件 |
| buy_sm_amount_rate | float | 未观察到 | 今日小单净流入占比(%) | % |  | 未扫描/无文件 |
| latest | float | 未观察到 | 最新价 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| net_amount | float | 未观察到 | 资金净流入(万元) | 万元 |  | 未扫描/无文件 |
| net_d5_amount | float | 未观察到 | 5日主力净额(万元) | 万元 |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |

## moneyflow_dc

个股资金流向（DC）；路径 `E:\QuantData\10_canonical\moneyflow_dc`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| buy_elg_amount | float | 未观察到 | 今日超大单净流入额（万元） | 万元 |  | 未扫描/无文件 |
| buy_elg_amount_rate | float | 未观察到 | 今日超大单净流入占比（%） | % |  | 未扫描/无文件 |
| buy_lg_amount | float | 未观察到 | 今日大单净流入额（万元） | 万元 |  | 未扫描/无文件 |
| buy_lg_amount_rate | float | 未观察到 | 今日大单净流入占比（%） | % |  | 未扫描/无文件 |
| buy_md_amount | float | 未观察到 | 今日中单净流入额（万元） | 万元 |  | 未扫描/无文件 |
| buy_md_amount_rate | float | 未观察到 | 今日中单净流入占比（%） | % |  | 未扫描/无文件 |
| buy_sm_amount | float | 未观察到 | 今日小单净流入额（万元） | 万元 |  | 未扫描/无文件 |
| buy_sm_amount_rate | float | 未观察到 | 今日小单净流入占比（%） | % |  | 未扫描/无文件 |
| close | float | 未观察到 | 最新价 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| net_amount | float | 未观察到 | 今日主力净流入额（万元） | 万元 |  | 未扫描/无文件 |
| net_amount_rate | float | 未观察到 | 今日主力净流入净占比（%） | % |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 | 是 | 未扫描/无文件 |

## moneyflow_ind_ths

行业资金流向（THS）；路径 `E:\QuantData\10_canonical\moneyflow_ind_ths`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| close | float | 未观察到 | 收盘指数 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| close_price | float | 未观察到 | 领涨股最新价 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| company_num | int | 未观察到 | 公司数量 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| industry | str | 未观察到 | 板块名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| lead_stock | str | 未观察到 | 领涨股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| net_amount | float | 未观察到 | 净额(亿元) | 亿元 |  | 未扫描/无文件 |
| net_buy_amount | float | 未观察到 | 流入资金(亿元) | 亿元 |  | 未扫描/无文件 |
| net_sell_amount | float | 未观察到 | 流出资金(亿元) | 亿元 |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 指数涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_change_stock | float | 未观察到 | 领涨股涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 板块代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## moneyflow_cnt_ths

板块资金流向（THS)；路径 `E:\QuantData\10_canonical\moneyflow_cnt_ths`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| close_price | float | 未观察到 | 最新价 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| company_num | int | 未观察到 | 公司数量 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| industry_index | float | 未观察到 | 板块指数点位 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| lead_stock | str | 未观察到 | 领涨股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| name | str | 未观察到 | 板块名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| net_amount | float | 未观察到 | 净额(亿元) | 亿元 |  | 未扫描/无文件 |
| net_buy_amount | float | 未观察到 | 流入资金(亿元) | 亿元 |  | 未扫描/无文件 |
| net_sell_amount | float | 未观察到 | 流出资金(亿元) | 亿元 |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 行业涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_change_stock | float | 未观察到 | 领涨股涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 板块代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## moneyflow_ind_dc

板块资金流向（DC）；路径 `E:\QuantData\10_canonical\moneyflow_ind_dc`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| buy_elg_amount | float | 未观察到 | 今日超大单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_elg_amount_rate | float | 未观察到 | 今日超大单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_lg_amount | float | 未观察到 | 今日大单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_lg_amount_rate | float | 未观察到 | 今日大单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_md_amount | float | 未观察到 | 今日中单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_md_amount_rate | float | 未观察到 | 今日中单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_sm_amount | float | 未观察到 | 今日小单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_sm_amount_rate | float | 未观察到 | 今日小单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_sm_amount_stock | str | 未观察到 | 今日主力净流入最大股 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| close | float | 未观察到 | 板块最新指数 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| content_type | str | 未观察到 | 数据类型 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| name | str | 未观察到 | 板块名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| net_amount | float | 未观察到 | 今日主力净流入 净额（元） | 元 |  | 未扫描/无文件 |
| net_amount_rate | float | 未观察到 | 今日主力净流入净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_change | float | 未观察到 | 板块涨跌幅（%） | % |  | 未扫描/无文件 |
| rank | int | 未观察到 | 序号 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | DC板块代码（行业、概念、地域） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## moneyflow_mkt_dc

大盘资金流向（DC）；路径 `E:\QuantData\10_canonical\moneyflow_mkt_dc`；自然键 `trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| buy_elg_amount | float | 未观察到 | 今日超大单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_elg_amount_rate | float | 未观察到 | 今日超大单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_lg_amount | float | 未观察到 | 今日大单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_lg_amount_rate | float | 未观察到 | 今日大单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_md_amount | float | 未观察到 | 今日中单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_md_amount_rate | float | 未观察到 | 今日中单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| buy_sm_amount | float | 未观察到 | 今日小单净流入 净额（元） | 元 |  | 未扫描/无文件 |
| buy_sm_amount_rate | float | 未观察到 | 今日小单净流入 净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| close_sh | float | 未观察到 | 上证收盘价（点） | 点 |  | 未扫描/无文件 |
| close_sz | float | 未观察到 | 深证收盘价（点） | 点 |  | 未扫描/无文件 |
| net_amount | float | 未观察到 | 今日主力净流入 净额（元） | 元 |  | 未扫描/无文件 |
| net_amount_rate | float | 未观察到 | 今日主力净流入净占比% | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_change_sh | float | 未观察到 | 上证涨跌幅(%) | % |  | 未扫描/无文件 |
| pct_change_sz | float | 未观察到 | 深证涨跌幅(%) | % |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD | 是 | 未扫描/无文件 |

## top_list

龙虎榜每日统计单；路径 `E:\QuantData\10_canonical\top_list`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 198701/198701 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 198701/198701 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 198701/198701 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/198701 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 198701/198701 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| amount | float | double | 总成交额 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| amount_rate | float | double | 龙虎榜成交额占比 | 未单独确认；参见含义/来源定义 |  | 106/198701 |
| close | float | double | 收盘价 | 未单独确认；参见含义/来源定义 |  | 52/198701 |
| float_values | float | double | 当日流通市值 | 未单独确认；参见含义/来源定义 |  | 33573/198701 |
| l_amount | float | double | 龙虎榜成交额 | 未单独确认；参见含义/来源定义 |  | 106/198701 |
| l_buy | float | double | 龙虎榜买入额 | 未单独确认；参见含义/来源定义 |  | 117/198701 |
| l_sell | float | double | 龙虎榜卖出额 | 未单独确认；参见含义/来源定义 |  | 1015/198701 |
| name | str | string | 名称 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| net_amount | float | double | 龙虎榜净买入额 | 未单独确认；参见含义/来源定义 |  | 106/198701 |
| net_rate | float | double | 龙虎榜净买额占比 | 未单独确认；参见含义/来源定义 |  | 106/198701 |
| pct_change | float | double | 涨跌幅 | 未单独确认；参见含义/来源定义 |  | 57/198701 |
| reason | str | string | 上榜理由 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| trade_date | str | string | 交易日期 | YYYYMMDD |  | 0/198701 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/198701 |
| turnover_rate | float | double | 换手率 | 未单独确认；参见含义/来源定义 |  | 1590/198701 |

## top_inst

龙虎榜机构交易单；路径 `E:\QuantData\10_canonical\top_inst`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2388918/2388918 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2388918/2388918 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2388918/2388918 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2388918 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2388918/2388918 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| buy | float | double | 买入额（元） | 元 |  | 341091/2388918 |
| buy_rate | float | double | 买入占总成交比例 | 未单独确认；参见含义/来源定义 |  | 355366/2388918 |
| exalter | str | string | 营业部名称 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| net_buy | float | double | 净成交额（元） | 元 |  | 0/2388918 |
| reason | str | string | 上榜理由 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| sell | float | double | 卖出额（元） | 元 |  | 345191/2388918 |
| sell_rate | float | double | 卖出占总成交比例 | 未单独确认；参见含义/来源定义 |  | 351296/2388918 |
| side | str | string | 买卖类型0：买入金额最大的前5名， 1：卖出金额最大的前5名 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |
| trade_date | str | string | 交易日期 | YYYYMMDD |  | 0/2388918 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/2388918 |

## block_trade

大宗交易；路径 `E:\QuantData\10_canonical\block_trade`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 559254/559254 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 559254/559254 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 559254/559254 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/559254 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 559254/559254 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| amount | float | double | 成交金额 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| buyer | str | string | 买方营业部 | 未单独确认；参见含义/来源定义 |  | 13454/559254 |
| price | float | double | 成交价 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| seller | str | string | 卖方营业部 | 未单独确认；参见含义/来源定义 |  | 13454/559254 |
| trade_date | str | string | 交易日历 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/559254 |
| vol | float | double | 成交量（万股） | 万股 |  | 0/559254 |

## repurchase

股票回购；路径 `E:\QuantData\10_canonical\repurchase`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 62681/62681 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1/62681 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 62681/62681 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/62681 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 62681/62681 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 1/62681 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| amount | float | double | 回购金额 | 未单独确认；参见含义/来源定义 |  | 3585/62681 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/62681 |
| end_date | str | string | 截止日期 | YYYYMMDD |  | 23226/62681 |
| exp_date | str | string | 过期日期 | YYYYMMDD |  | 57238/62681 |
| high_limit | float | double | 回购最高价 | 未单独确认；参见含义/来源定义 |  | 7130/62681 |
| low_limit | float | double | 回购最低价 | 未单独确认；参见含义/来源定义 |  | 18602/62681 |
| proc | str | string | 进度 | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/62681 |
| vol | float | double | 回购数量 | 未单独确认；参见含义/来源定义 |  | 23319/62681 |

## pledge_stat

股权质押统计数据；路径 `E:\QuantData\10_canonical\pledge_stat`；自然键 `ts_code,end_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1646734/1646734 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1646734/1646734 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 1646734/1646734 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/1646734 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 1646734/1646734 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 88/1646734 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| end_date | str | string | 截止日期 | YYYYMMDD | 是 | 0/1646734 |
| pledge_count | int | double | 质押次数 | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| pledge_ratio | float | double | 质押比例（%） | % |  | 0/1646734 |
| rest_pledge | float | double | 限售股份质押数量（万） | 未单独确认；参见含义/来源定义 |  | 0/1646734 |
| total_share | float | double | 总股本（万股） | 万股 |  | 0/1646734 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 | 是 | 0/1646734 |
| unrest_pledge | float | double | 无限售股质押数量（万） | 未单独确认；参见含义/来源定义 |  | 0/1646734 |

## pledge_detail

股权质押明细数据；路径 `E:\QuantData\10_canonical\pledge_detail`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 220409/220409 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 220409/220409 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/220409 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 220409/220409 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/220409 |
| end_date | str | string | 质押结束日期 | YYYYMMDD |  | 88351/220409 |
| h_total_ratio | float | double | 持股总数占总股本比例 | 未单独确认；参见含义/来源定义 |  | 7914/220409 |
| holder_name | str | string | 股东名称 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| holding_amount | float | double | 持股总数（万股） | 万股 |  | 5570/220409 |
| is_buyback | str | string | 是否回购（0否 1是） | 未单独确认；参见含义/来源定义 |  | 1615/220409 |
| is_release | str | string | 是否已解押 | 未单独确认；参见含义/来源定义 |  | 0/220409 |
| p_total_ratio | float | double | 本次质押占总股本比例 | 未单独确认；参见含义/来源定义 |  | 53483/220409 |
| pledge_amount | float | double | 质押数量（万股） | 万股 |  | 0/220409 |
| pledged_amount | float | double | 质押总数（万股） | 万股 |  | 7062/220409 |
| pledgor | str | string | 质押方 | 未单独确认；参见含义/来源定义 |  | 1447/220409 |
| release_date | str | string | 解押日期 | YYYYMMDD |  | 41496/220409 |
| start_date | str | string | 质押开始日期 | YYYYMMDD |  | 3155/220409 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/220409 |

## stk_holdernumber

股东人数；路径 `E:\QuantData\10_canonical\stk_holdernumber`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 473194/473194 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1/473194 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 473194/473194 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 1/473194 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 473194/473194 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/473194 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/473194 |
| end_date | str | string | 截止日期 | YYYYMMDD |  | 0/473194 |
| holder_num | int | double | 股东户数 | 未单独确认；参见含义/来源定义 |  | 24/473194 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/473194 |

## stk_holdertrade

股东增减持；路径 `E:\QuantData\10_canonical\stk_holdertrade`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 160788/160788 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 160788/160788 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/160788 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 160788/160788 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| after_ratio | float | double | 变动后占流通比例（%） | % |  | 27931/160788 |
| after_share | float | double | 变动后持股 | 未单独确认；参见含义/来源定义 |  | 21544/160788 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/160788 |
| avg_price | float | double | 平均价格 | 未单独确认；参见含义/来源定义 |  | 45230/160788 |
| begin_date | str | string | 增减持开始日期 | YYYYMMDD |  | 4020/160788 |
| change_ratio | float | double | 占流通比例（%） | % |  | 50/160788 |
| change_vol | float | double | 变动数量 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| close_date | str | string | 增减持结束日期 | YYYYMMDD |  | 0/160788 |
| holder_name | str | string | 股东名称 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| holder_type | str | string | 股东类型G高管P个人C公司 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| in_de | str | string | 类型IN增持DE减持 | 未单独确认；参见含义/来源定义 |  | 0/160788 |
| total_share | float | double | 持股总数 | 未单独确认；参见含义/来源定义 |  | 18358/160788 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/160788 |

## top10_holders

前十大股东；路径 `E:\QuantData\10_canonical\top10_holders`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2319216/2319216 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2319216/2319216 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2319216 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2319216/2319216 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/2319216 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| hold_amount | float | double | 持有数量（股） | 股 |  | 0/2319216 |
| hold_change | float | double | 持股变动 | 未单独确认；参见含义/来源定义 |  | 430797/2319216 |
| hold_float_ratio | float | double | 占流通股本比例(%) | % |  | 374890/2319216 |
| hold_ratio | float | double | 占总股本比例(%) | % |  | 0/2319216 |
| holder_name | str | string | 股东名称 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |
| holder_type | str | string | 股东类型 | 未单独确认；参见含义/来源定义 |  | 2/2319216 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/2319216 |

## top10_floatholders

前十大流通股东；路径 `E:\QuantData\10_canonical\top10_floatholders`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2098029/2098029 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2098029/2098029 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2098029 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2098029/2098029 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/2098029 |
| end_date | str | string | 报告期 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| hold_amount | float | double | 持有数量（股） | 股 |  | 10/2098029 |
| hold_change | float | double | 持股变动（0表示不变，空值表示 新进） | 未单独确认；参见含义/来源定义 |  | 579551/2098029 |
| hold_float_ratio | float | double | 占流通股本比例(%) | % |  | 20655/2098029 |
| hold_ratio | float | double | 占总股本比例(%) | % |  | 0/2098029 |
| holder_name | str | string | 股东名称 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| holder_type | str | string | 股东类型 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/2098029 |

## share_float

限售股解禁；路径 `E:\QuantData\10_canonical\share_float`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 6270894/6270894 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 6270894/6270894 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/6270894 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 6270894/6270894 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/6270894 |
| float_date | str | string | 解禁日期 | YYYYMMDD |  | 0/6270894 |
| float_ratio | float | double | 流通股份占总股本比率(%) | % |  | 166673/6270894 |
| float_share | float | double | 流通股份(股) | 股 |  | 2/6270894 |
| holder_name | str | string | 股东名称 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| share_type | str | string | 股份类型 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |
| ts_code | str | string | TS代码 | 未单独确认；参见含义/来源定义 |  | 0/6270894 |

## stk_rewards

管理层薪酬和持股；路径 `E:\QuantData\10_canonical\stk_rewards`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 1642908/1642908 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 122/1642908 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 1642908/1642908 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 122/1642908 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 1642908/1642908 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| ann_date | str | null,string | 公告日期 | YYYYMMDD |  | 122/1642908 |
| end_date | str | string | 截止日期 | YYYYMMDD |  | 0/1642908 |
| hold_vol | float | double | 持股数（股） | 股 |  | 24318/1642908 |
| name | str | string | 姓名 | 未单独确认；参见含义/来源定义 |  | 0/1642908 |
| reward | float | double | 报酬（元） | 元 |  | 477794/1642908 |
| title | str | string | 职务 | 未单独确认；参见含义/来源定义 |  | 53229/1642908 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/1642908 |

## stk_managers

上市公司管理层；路径 `E:\QuantData\10_canonical\stk_managers`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 363487/363487 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 363487/363487 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/363487 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 363487/363487 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/363487 |
| begin_date | str | string | 上任日期 | YYYYMMDD |  | 379/363487 |
| birthday | str | string | 出生年月 | 未单独确认；参见含义/来源定义 |  | 8779/363487 |
| edu | str | string | 学历 | 未单独确认；参见含义/来源定义 |  | 17814/363487 |
| end_date | str | string | 离任日期 | YYYYMMDD |  | 170526/363487 |
| gender | str | string | 性别 | 未单独确认；参见含义/来源定义 |  | 5937/363487 |
| lev | str | string | 岗位类别 | 未单独确认；参见含义/来源定义 |  | 2/363487 |
| name | str | string | 姓名 | 未单独确认；参见含义/来源定义 |  | 0/363487 |
| national | str | string | 国籍 | 未单独确认；参见含义/来源定义 |  | 18371/363487 |
| resume | str | string | 个人简历 | 未单独确认；参见含义/来源定义 |  | 242/363487 |
| title | str | string | 岗位 | 未单独确认；参见含义/来源定义 |  | 2/363487 |
| ts_code | str | string | TS股票代码 | 未单独确认；参见含义/来源定义 |  | 0/363487 |

## stk_seasoned

股票增发；路径 `E:\QuantData\10_canonical\stk_seasoned`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 9736/9736 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 28/9736 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 9736/9736 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/9736 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 9736/9736 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 28/9736 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| a_inv_plac_qty | str | null,string | A类投资者配售股数（股） | 股 |  | 9735/9736 |
| ann_date | str | string | 公告日期 | YYYYMMDD |  | 0/9736 |
| apply_date | str | string | 申购日 | 未单独确认；参见含义/来源定义 |  | 7458/9736 |
| b_inv_plac_qty | str | null,string | B类投资者配售股数（股） | 股 |  | 9735/9736 |
| board_approval_dt | str | string | 董事会审议通过并公告日期 | YYYYMMDD |  | 2109/9736 |
| clw_between_inst_pub | str | null,string | 网上网下回拨股数(股) | 股 |  | 9736/9736 |
| csrc_approval_dt | str | string | 证监会批准公告日 | 未单独确认；参见含义/来源定义 |  | 5190/9736 |
| cur_stage | str | string | 进程:意向;董事会预案;监管审批;实施;终止 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| ex_right_dt | str | null,string | 除权日 | 未单独确认；参见含义/来源定义 |  | 9736/9736 |
| first_ann_date | str | string | 首次发布公告日期 | YYYYMMDD |  | 0/9736 |
| fo_exp_audit | float | double | 审计费（元） | 元 |  | 8033/9736 |
| fo_exp_inst | float | double | 中介机构费（元） | 元 |  | 8953/9736 |
| fo_exp_legal | float | double | 律师费（元） | 元 |  | 8098/9736 |
| fo_exp_other | float | double | 其他费用（元） | 元 |  | 7747/9736 |
| fo_exp_per_share | float | double | 每股发行费（元） | 元 |  | 6412/9736 |
| fo_exp_pub | float | double | 上网发行费（元） | 元 |  | 9719/9736 |
| fo_exp_reg | float | double | 股票登记费（元） | 元 |  | 8808/9736 |
| fo_exp_total | float | double | 发行费用总额（元） | 元 |  | 6410/9736 |
| fo_investor | str | string | 预计发行对象 | 未单独确认；参见含义/来源定义 |  | 3/9736 |
| fo_price_act | float | double | 发行价（元） | 元 |  | 5532/9736 |
| fo_price_high | float | double | 预计发行价上限（元） | 元 |  | 6449/9736 |
| fo_price_low | float | double | 预计发行价下限（元） | 元 |  | 5569/9736 |
| fo_price_ratio | float | double | 预计价格相对基准价格比例（%） | % |  | 138/9736 |
| fo_purpose | str | string | 增发目的 | 未单独确认；参见含义/来源定义 |  | 3/9736 |
| fo_raise_net_act | float | double | 募集资金净额（元） | 元 |  | 5532/9736 |
| fo_raise_total | float | double | 预计募集资金总额（元） | 元 |  | 245/9736 |
| fo_raise_total_act | float | double | 募集资金总额（元） | 元 |  | 5532/9736 |
| fo_stock_type | str | string | 增发A股类型 | 未单独确认；参见含义/来源定义 |  | 773/9736 |
| fo_type | str | string | 增发类别:公开;非公开 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| fo_vol_act | str | string | 发行量（股） | 股 |  | 5532/9736 |
| fo_vol_high | str | string | 预计发行量上限（股） | 股 |  | 3320/9736 |
| fo_vol_low | str | string | 预计发行量下限（股） | 股 |  | 7966/9736 |
| inst_oversub_times | float | double | 专业机构超额认购倍数（倍） | 倍 |  | 9731/9736 |
| inst_plac_qty | str | null,string | 专业机构配售股数（股） | 股 |  | 9731/9736 |
| inst_sub_eff_cnt | str | null,string | 专业机构有效申购户数（户） | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| inst_sub_eff_total | str | null,string | 专业机构有效申购总量（股） | 股 |  | 9731/9736 |
| issue_obj_type | str | string | 发行对象类型 全体投资者 大股东及大股东关联方 机构投资者 自然人 | 未单独确认；参见含义/来源定义 |  | 778/9736 |
| list_circ_qty | str | null,string | 本次上市流通股数（股） | 股 |  | 9691/9736 |
| new_share_list_dt | str | string | 新增股份上市日期 | YYYYMMDD |  | 5546/9736 |
| offer_intent_pub_dt | str | null,string | 发行意向文件披露日期 | YYYYMMDD |  | 9732/9736 |
| old_sh_pre_plac_dt | str | null,string | 老股东优先配售日期 | YYYYMMDD |  | 9731/9736 |
| old_sh_pre_plac_qty | str | null,string | 老股东优先配售股数（股） | 股 |  | 9731/9736 |
| old_sh_pre_plac_ratio | float | double | 老股东优先配售比例 % | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| onl_issue_date | str | null,string | 网上发行日期 | YYYYMMDD |  | 9731/9736 |
| onl_pch_excess | float | double | 网上发行超额认购倍数 | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| onl_pch_num | str | null,string | 网上发行有效申购户数（户） | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| onl_pch_vol | str | null,string | 网上发行有效申购数量（股） | 股 |  | 9731/9736 |
| onl_winning_rate | float | double | 网上发行中签率（%） | % |  | 9731/9736 |
| pe_issue | float | double | 增发市盈率（按增发前总股本） | 按增发前总股本 |  | 9736/9736 |
| plan_chg_ann_dt | str | string | 方案变动公告日期 | YYYYMMDD |  | 0/9736 |
| plan_chg_type | str | string | 方案变动类型 方案调整 增发变更 推迟 终止 | 未单独确认；参见含义/来源定义 |  | 5306/9736 |
| price_basis | str | string | 价格制定依据 | 未单独确认；参见含义/来源定义 |  | 4/9736 |
| pricing_base_dt | str | string | 定价基准日 | 未单独确认；参见含义/来源定义 |  | 3810/9736 |
| pricing_method | str | string | 定价方式 估值定价 协商定价 市价参考 询价方式投 限价约束 | 未单独确认；参见含义/来源定义 |  | 877/9736 |
| proj_info_source | str | string | 信息来源 | 未单独确认；参见含义/来源定义 |  | 2412/9736 |
| prospectus_pub_dt | str | null,string | 募集说明书对外披露日期 | YYYYMMDD |  | 9735/9736 |
| pub_plac_qty | str | null,string | 网上发行股数(股） | 股 |  | 9731/9736 |
| right_reg_dt | str | string | 股权登记日 | 未单独确认；参见含义/来源定义 |  | 5546/9736 |
| sasac_approval_dt | str | string | 国资委通过公告日 | 未单独确认；参见含义/来源定义 |  | 8679/9736 |
| sh_approval_dt | str | string | 股东大会决议公告日期 | YYYYMMDD |  | 959/9736 |
| sub_method | str | string | 认购方式 纯现金 资产类 其他 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| ts_code | str | string | 股票代码 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| update_flag | str | string | 更新标识 默认为0 有更新时为1 | 未单独确认；参见含义/来源定义 |  | 0/9736 |
| uw_end_dt | str | null,string | 承销期截止日 | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| uw_fee | float | double | 承销保荐费（元） | 元 |  | 7319/9736 |
| uw_mode | str | null,string | 承销方式 券商包销 非包销代销 上市公司自销 | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| uw_start_dt | str | null,string | 承销期起始日 | 未单独确认；参见含义/来源定义 |  | 9731/9736 |
| valid_end_dt | str | string | 预案有效期截止日期 | YYYYMMDD |  | 3401/9736 |
| valid_st_dt | str | string | 预案有效期起始日期 | YYYYMMDD |  | 1127/9736 |

## stk_shock

个股异常波动；路径 `E:\QuantData\10_canonical\stk_shock`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| period | str | 未观察到 | 异常期间 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| reason | str | 未观察到 | 异常说明 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 公告日期 | YYYYMMDD |  | 未扫描/无文件 |
| trade_market | str | 未观察到 | 交易所 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## stk_high_shock

个股严重异常波动；路径 `E:\QuantData\10_canonical\stk_high_shock`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| period | str | 未观察到 | 异常期间 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| reason | str | 未观察到 | 异常说明 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 公告日期 | YYYYMMDD |  | 未扫描/无文件 |
| trade_market | str | 未观察到 | 交易所 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## stk_alert

交易所重点提示证券；路径 `E:\QuantData\10_canonical\stk_alert`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| end_date | str | 未观察到 | 交易所重点提示参考截至日期 | YYYYMMDD |  | 未扫描/无文件 |
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| start_date | str | 未观察到 | 交易所重点提示起始日期 | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| type | str | 未观察到 | 提示类型 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |

## limit_list_d

涨跌停和炸板数据；路径 `E:\QuantData\10_canonical\limit_list_d`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| amount | float | 未观察到 | 成交额 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| close | float | 未观察到 | 收盘价 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| fd_amount | float | 未观察到 | 封单金额（以涨停价买入挂单的资金总量） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| first_time | str | 未观察到 | 首次封板时间（跌停无此数据） | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| float_mv | float | 未观察到 | 流通市值 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| industry | str | 未观察到 | 所属行业 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| last_time | str | 未观察到 | 最后封板时间 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| limit | str | 未观察到 | D跌停U涨停Z炸板 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| limit_amount | float | 未观察到 | 板上成交金额(成交价格为该股票跌停价的所有成交额的总和，涨停无此数据) | 成交价格为该股票跌停价的所有成交额的总和，涨停无此数据 |  | 未扫描/无文件 |
| limit_times | int | 未观察到 | 连板数（个股连续封板数量） | 个股连续封板数量 |  | 未扫描/无文件 |
| name | str | 未观察到 | 股票名称 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| open_times | int | 未观察到 | 炸板次数(跌停为开板次数) | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| pct_chg | float | 未观察到 | 涨跌幅 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| total_mv | float | 未观察到 | 总市值 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| trade_date | str | 未观察到 | 交易日期 | YYYYMMDD |  | 未扫描/无文件 |
| ts_code | str | 未观察到 | 股票代码 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| turnover_ratio | float | 未观察到 | 换手率 | 未单独确认；参见含义/来源定义 |  | 未扫描/无文件 |
| up_stat | str | 未观察到 | 涨停统计（N/T T天有N次涨停） | N/T T天有N次涨停 |  | 未扫描/无文件 |

## shibor

Shibor利率；路径 `E:\QuantData\10_canonical\shibor`；自然键 `date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2904/2904 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2904/2904 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2904/2904 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2904 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2904/2904 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2904 |
| date | str | string | 日期 | YYYYMMDD | 是 | 0/2904 |
| on | float | double | 隔夜 | 未单独确认；参见含义/来源定义 |  | 0/2904 |

## shibor_quote

Shibor报价数据；路径 `E:\QuantData\10_canonical\shibor_quote`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 5830/5830 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 5830/5830 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 5830/5830 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/5830 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 5830/5830 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| bank | str | string | 报价银行 | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| date | str | string | 日期 | YYYYMMDD |  | 0/5830 |
| on_a | float | double | 隔夜_Ask | 未单独确认；参见含义/来源定义 |  | 0/5830 |
| on_b | float | double | 隔夜_Bid | 未单独确认；参见含义/来源定义 |  | 0/5830 |

## shibor_lpr

LPR贷款基础利率；路径 `E:\QuantData\10_canonical\shibor_lpr`；自然键 `date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 365/365 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 365/365 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/365 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/365 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 365/365 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/365 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/365 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/365 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 365/365 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/365 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/365 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/365 |
| date | str | string | 日期 | YYYYMMDD | 是 | 0/365 |

## cn_gdp

国内生产总值（GDP）；路径 `E:\QuantData\10_canonical\cn_gdp`；自然键 `quarter`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 46/46 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 46/46 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 46/46 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/46 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/46 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/46 |
| gdp | float | double | GDP累计值（亿元） | 亿元 |  | 0/46 |
| gdp_yoy | float | double | 当季同比增速（%） | % |  | 0/46 |
| pi | float | double | 第一产业累计值（亿元） | 亿元 |  | 0/46 |
| pi_yoy | float | double | 第一产业同比增速（%） | % |  | 0/46 |
| quarter | str | string | 季度 | 未单独确认；参见含义/来源定义 | 是 | 0/46 |
| si | float | double | 第二产业累计值（亿元） | 亿元 |  | 0/46 |
| si_yoy | float | double | 第二产业同比增速（%） | % |  | 0/46 |
| ti | float | double | 第三产业累计值（亿元） | 亿元 |  | 0/46 |
| ti_yoy | float | double | 第三产业同比增速（%） | % |  | 0/46 |

## cn_cpi

居民消费价格指数（CPI）；路径 `E:\QuantData\10_canonical\cn_cpi`；自然键 `month`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/140 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| cnt_accu | float | double | 农村累计值 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| cnt_mom | float | double | 农村环比（%） | % |  | 0/140 |
| cnt_val | float | double | 农村当月值 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| cnt_yoy | float | double | 农村同比（%） | % |  | 0/140 |
| month | str | string | 月份YYYYMM | 未单独确认；参见含义/来源定义 | 是 | 0/140 |
| nt_accu | float | double | 全国累计值 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| nt_mom | float | double | 全国环比（%） | % |  | 0/140 |
| nt_val | float | double | 全国当月值 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| nt_yoy | float | double | 全国同比（%） | % |  | 0/140 |
| town_accu | float | double | 城市累计值 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| town_mom | float | double | 城市环比（%） | % |  | 0/140 |
| town_val | float | double | 城市当月值 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| town_yoy | float | double | 城市同比（%） | % |  | 0/140 |

## cn_ppi

工业生产者出厂价格指数（PPI）；路径 `E:\QuantData\10_canonical\cn_ppi`；自然键 `month`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/140 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| month | str | string | 月份YYYYMM | 未单独确认；参见含义/来源定义 | 是 | 0/140 |
| ppi_accu | float | double | PPI：全部工业品：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_accu | float | double | PPI：生活资料：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_adu_accu | float | double | PPI：生活资料：一般日用品类：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_adu_mom | float | double | PPI：生活资料：一般日用品类：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_adu_yoy | float | double | PPI：生活资料：一般日用品类：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_c_accu | float | double | PPI：生活资料：衣着类：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_c_mom | float | double | PPI：生活资料：衣着类：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_c_yoy | float | double | PPI：生活资料：衣着类：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_dcg_accu | float | double | PPI：生活资料：耐用消费品类：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_dcg_mom | float | double | PPI：生活资料：耐用消费品类：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_dcg_yoy | float | double | PPI：生活资料：耐用消费品类：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_f_accu | float | double | PPI：生活资料：食品类：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_f_mom | float | double | PPI：生活资料：食品类：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_f_yoy | float | double | PPI：生活资料：食品类：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_mom | float | double | PPI：生活资料：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_cg_yoy | float | double | PPI：生活资料：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mom | float | double | PPI：全部工业品：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_accu | float | double | PPI：生产资料：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_mom | float | double | PPI：生产资料：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_p_accu | float | double | PPI：生产资料：加工业：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_p_mom | float | double | PPI：生产资料：加工业：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_p_yoy | float | double | PPI：生产资料：加工业：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_qm_accu | float | double | PPI：生产资料：采掘业：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_qm_mom | float | double | PPI：生产资料：采掘业：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_qm_yoy | float | double | PPI：生产资料：采掘业：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_rm_accu | float | double | PPI：生产资料：原料业：累计同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_rm_mom | float | double | PPI：生产资料：原料业：环比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_rm_yoy | float | double | PPI：生产资料：原料业：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_mp_yoy | float | double | PPI：生产资料：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| ppi_yoy | float | double | PPI：全部工业品：当月同比 | 未单独确认；参见含义/来源定义 |  | 0/140 |

## cn_m

货币供应量（月）；路径 `E:\QuantData\10_canonical\cn_m`；自然键 `month`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/140 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| m0 | float | double | M0（亿元） | 亿元 |  | 0/140 |
| m0_mom | float | double | M0环比（%） | % |  | 0/140 |
| m0_yoy | float | double | M0同比（%） | % |  | 0/140 |
| m1 | float | double | M1（亿元） | 亿元 |  | 0/140 |
| m1_mom | float | double | M1环比（%） | % |  | 0/140 |
| m1_yoy | float | double | M1同比（%） | % |  | 0/140 |
| m2 | float | double | M2（亿元） | 亿元 |  | 0/140 |
| m2_mom | float | double | M2环比（%） | % |  | 0/140 |
| m2_yoy | float | double | M2同比（%） | % |  | 0/140 |
| month | str | string | 月份YYYYMM | 未单独确认；参见含义/来源定义 | 是 | 0/140 |

## cn_pmi

采购经理指数（PMI）；路径 `E:\QuantData\10_canonical\cn_pmi`；自然键 `month`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 141/141 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 141/141 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 141/141 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/141 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| month | str | string | 月份YYYYMM | 未单独确认；参见含义/来源定义 | 是 | 0/141 |
| pmi010000 | float | double | 制造业PMI | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010100 | float | double | 制造业PMI:企业规模/大型企业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010200 | float | double | 制造业PMI:企业规模/中型企业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010300 | float | double | 制造业PMI:企业规模/小型企业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010400 | float | double | 制造业PMI:构成指数/生产指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010401 | float | double | 制造业PMI:构成指数/生产指数:企业规模/大型企业 | 未单独确认；参见含义/来源定义 |  | 18/141 |
| pmi010402 | float | double | 制造业PMI:构成指数/生产指数:企业规模/中型企业 | 未单独确认；参见含义/来源定义 |  | 27/141 |
| pmi010403 | float | double | 制造业PMI:构成指数/生产指数:企业规模/小型企业 | 未单独确认；参见含义/来源定义 |  | 25/141 |
| pmi010500 | float | double | 制造业PMI:构成指数/新订单指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010501 | float | double | 制造业PMI:构成指数/新订单指数:企业规模/大型企业 | 未单独确认；参见含义/来源定义 |  | 21/141 |
| pmi010502 | float | double | 制造业PMI:构成指数/新订单指数:企业规模/中型企业 | 未单独确认；参见含义/来源定义 |  | 27/141 |
| pmi010503 | float | double | 制造业PMI:构成指数/新订单指数:企业规模/小型企业 | 未单独确认；参见含义/来源定义 |  | 25/141 |
| pmi010600 | float | double | 制造业PMI:构成指数/供应商配送时间指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010601 | float | double | 制造业PMI:构成指数/供应商配送时间指数:企业规模/大型企业 | 未单独确认；参见含义/来源定义 |  | 27/141 |
| pmi010602 | float | double | 制造业PMI:构成指数/供应商配送时间指数:企业规模/中型企业 | 未单独确认；参见含义/来源定义 |  | 27/141 |
| pmi010603 | float | double | 制造业PMI:构成指数/供应商配送时间指数:企业规模/小型企业 | 未单独确认；参见含义/来源定义 |  | 27/141 |
| pmi010700 | float | double | 制造业PMI:构成指数/原材料库存指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010701 | float | double | 制造业PMI:构成指数/原材料库存指数:企业规模/大型企业 | 未单独确认；参见含义/来源定义 |  | 29/141 |
| pmi010702 | float | double | 制造业PMI:构成指数/原材料库存指数:企业规模/中型企业 | 未单独确认；参见含义/来源定义 |  | 29/141 |
| pmi010703 | float | double | 制造业PMI:构成指数/原材料库存指数:企业规模/小型企业 | 未单独确认；参见含义/来源定义 |  | 29/141 |
| pmi010800 | float | double | 制造业PMI:构成指数/从业人员指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi010801 | float | double | 制造业PMI:构成指数/从业人员指数:企业规模/大型企业 | 未单独确认；参见含义/来源定义 |  | 30/141 |
| pmi010802 | float | double | 制造业PMI:构成指数/从业人员指数:企业规模/中型企业 | 未单独确认；参见含义/来源定义 |  | 30/141 |
| pmi010803 | float | double | 制造业PMI:构成指数/从业人员指数:企业规模/小型企业 | 未单独确认；参见含义/来源定义 |  | 30/141 |
| pmi010900 | float | double | 制造业PMI:其他/新出口订单 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011000 | float | double | 制造业PMI:其他/进口 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011100 | float | double | 制造业PMI:其他/采购量 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011200 | float | double | 制造业PMI:其他/主要原材料购进价格 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011300 | float | double | 制造业PMI:其他/出厂价格 | 未单独确认；参见含义/来源定义 |  | 13/141 |
| pmi011400 | float | double | 制造业PMI:其他/产成品库存 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011500 | float | double | 制造业PMI:其他/在手订单 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011600 | float | double | 制造业PMI:其他/生产经营活动预期 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi011700 | float | double | 制造业PMI:分行业/装备制造业 | 未单独确认；参见含义/来源定义 |  | 42/141 |
| pmi011800 | float | double | 制造业PMI:分行业/高技术制造业 | 未单独确认；参见含义/来源定义 |  | 46/141 |
| pmi011900 | float | double | 制造业PMI:分行业/基础原材料制造业 | 未单独确认；参见含义/来源定义 |  | 79/141 |
| pmi012000 | float | double | 制造业PMI:分行业/消费品制造业 | 未单独确认；参见含义/来源定义 |  | 50/141 |
| pmi020100 | float | double | 非制造业PMI:商务活动 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020101 | float | double | 非制造业PMI:商务活动:分行业/建筑业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020102 | float | double | 非制造业PMI:商务活动:分行业/服务业业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020200 | float | double | 非制造业PMI:新订单指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020201 | float | double | 非制造业PMI:新订单指数:分行业/建筑业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020202 | float | double | 非制造业PMI:新订单指数:分行业/服务业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020300 | float | double | 非制造业PMI:投入品价格指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020301 | float | double | 非制造业PMI:投入品价格指数:分行业/建筑业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020302 | float | double | 非制造业PMI:投入品价格指数:分行业/服务业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020400 | float | double | 非制造业PMI:销售价格指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020401 | float | double | 非制造业PMI:销售价格指数:分行业/建筑业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020402 | float | double | 非制造业PMI:销售价格指数:分行业/服务业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020500 | float | double | 非制造业PMI:从业人员指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020501 | float | double | 非制造业PMI:从业人员指数:分行业/建筑业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020502 | float | double | 非制造业PMI:从业人员指数:分行业/服务业 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020600 | float | double | 非制造业PMI:业务活动预期指数 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020601 | float | double | 非制造业PMI:业务活动预期指数:分行业/建筑业 | 未单独确认；参见含义/来源定义 |  | 29/141 |
| pmi020602 | float | double | 非制造业PMI:业务活动预期指数:分行业/服务业 | 未单独确认；参见含义/来源定义 |  | 29/141 |
| pmi020700 | float | double | 非制造业PMI:新出口订单 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020800 | float | double | 非制造业PMI:在手订单 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi020900 | float | double | 非制造业PMI:存货 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi021000 | float | double | 非制造业PMI:供应商配送时间 | 未单独确认；参见含义/来源定义 |  | 0/141 |
| pmi030000 | float | double | 中国综合PMI:产出指数 | 未单独确认；参见含义/来源定义 |  | 24/141 |

## sf_month

社融增量（月度）；路径 `E:\QuantData\10_canonical\sf_month`；自然键 `month`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 140/140 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/140 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/140 |
| inc_cumval | float | double | 社融增量累计值（亿元） | 亿元 |  | 0/140 |
| inc_month | float | double | 社融增量当月值（亿元） | 亿元 |  | 0/140 |
| month | str | string | 月度 | 未单独确认；参见含义/来源定义 | 是 | 0/140 |
| stk_endval | float | double | 社融存量期末值（万亿元） | 万亿元 |  | 8/140 |

## cn_schedule

中国经济数据发布日程；路径 `E:\QuantData\10_canonical\cn_schedule`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 131/131 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 131/131 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 131/131 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/131 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/131 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/131 |
| data_api | str | string | tushare对应接口 | 未单独确认；参见含义/来源定义 |  | 15/131 |
| issuing_org | str | string | 发布单位 | 未单独确认；参见含义/来源定义 |  | 0/131 |
| month | str | string | 月份YYYYMM | 未单独确认；参见含义/来源定义 |  | 0/131 |
| publish_date | str | string | 发布日期 | YYYYMMDD |  | 0/131 |
| title | str | string | 发布数据 | 未单独确认；参见含义/来源定义 |  | 0/131 |

## wz_index

温州民间借贷利率；路径 `E:\QuantData\10_canonical\wz_index`；自然键 `date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2703/2703 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 2703/2703 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 2703/2703 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/2703 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 2703/2703 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| aa_rate | float | double | 农村互助会互助金费率 | 未单独确认；参见含义/来源定义 |  | 849/2703 |
| center_rate | float | double | 民间借贷服务中心利率 | 未单独确认；参见含义/来源定义 |  | 849/2703 |
| cm_rate | float | double | 民间资本管理公司融资价格 | 未单独确认；参见含义/来源定义 |  | 849/2703 |
| comp_rate | float | double | 温州民间融资综合利率指数 (%，下同) | %，下同 |  | 0/2703 |
| date | str | string | 日期 | YYYYMMDD | 是 | 0/2703 |
| long_rate | float | double | 温州地区民间借贷分期限利率（长期） | 未单独确认；参见含义/来源定义 |  | 24/2703 |
| m12_rate | float | double | 温州地区民间借贷分期限利率（一年期） | 一年期 |  | 0/2703 |
| m1_rate | float | double | 温州地区民间借贷分期限利率（一月期） | 未单独确认；参见含义/来源定义 |  | 0/2703 |
| m3_rate | float | double | 温州地区民间借贷分期限利率（三月期） | 未单独确认；参见含义/来源定义 |  | 27/2703 |
| m6_rate | float | double | 温州地区民间借贷分期限利率（六月期） | 未单独确认；参见含义/来源定义 |  | 1/2703 |
| micro_rate | float | double | 小额贷款公司放款利率 | 未单独确认；参见含义/来源定义 |  | 849/2703 |
| om_rate | float | double | 其他市场主体利率 | 未单独确认；参见含义/来源定义 |  | 849/2703 |
| sdb_rate | float | double | 社会直接借贷利率 | 未单独确认；参见含义/来源定义 |  | 1/2703 |

## gz_index

广州民间借贷利率；路径 `E:\QuantData\10_canonical\gz_index`；自然键 `date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 644/644 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 644/644 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/644 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/644 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 644/644 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/644 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/644 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/644 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 644/644 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/644 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/644 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/644 |
| d10_rate | float | double | 小额贷市场平均利率（十天） （单位：%，下同） | 十天; 单位：%，下同 |  | 0/644 |
| date | str | string | 日期 | YYYYMMDD | 是 | 0/644 |
| long_rate | float | double | 小额贷市场平均利率（长期） | 未单独确认；参见含义/来源定义 |  | 0/644 |
| m12_rate | float | double | 小额贷市场平均利率（一年期） | 一年期 |  | 0/644 |
| m1_rate | float | double | 小额贷市场平均利率（一月期） | 未单独确认；参见含义/来源定义 |  | 0/644 |
| m3_rate | float | double | 小额贷市场平均利率（三月期） | 未单独确认；参见含义/来源定义 |  | 0/644 |
| m6_rate | float | double | 小额贷市场平均利率（六月期） | 未单独确认；参见含义/来源定义 |  | 0/644 |

## daily_info

沪深市场每日交易统计；路径 `E:\QuantData\10_canonical\daily_info`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 55398/55398 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 55398/55398 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 55398/55398 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/55398 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 55398/55398 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| amount | float | double | 交易金额（亿元） | 亿元 |  | 2689/55398 |
| com_count | int | double | 挂牌数 | 未单独确认；参见含义/来源定义 |  | 3980/55398 |
| exchange | str | string | 交易所（SH上交所 SZ深交所） | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| float_mv | float | double | 流通市值（亿元） | 亿元 |  | 19910/55398 |
| float_share | float | double | 流通股本（亿股） | 亿股 |  | 30358/55398 |
| pe | float | double | 平均市盈率 | 未单独确认；参见含义/来源定义 |  | 35231/55398 |
| total_mv | float | double | 总市值（亿元） | 亿元 |  | 19910/55398 |
| total_share | float | double | 总股本（亿股） | 亿股 |  | 30358/55398 |
| tr | float | double | 换手率（％），注：深交所暂无此列 | 未单独确认；参见含义/来源定义 |  | 41455/55398 |
| trade_date | str | string | 交易日期 | YYYYMMDD |  | 0/55398 |
| trans_count | int | double | 成交笔数（万笔） | 未单独确认；参见含义/来源定义 |  | 37294/55398 |
| ts_code | str | string | 市场代码 | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| ts_name | str | string | 市场名称 | 未单独确认；参见含义/来源定义 |  | 0/55398 |
| vol | float | double | 成交量（亿股） | 亿股 |  | 5539/55398 |

## sz_daily_info

深圳市场每日交易情况；路径 `E:\QuantData\10_canonical\sz_daily_info`；自然键 `内容身份`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 41454/41454 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 41454/41454 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| _event_available_at | 元数据 | timestamp[ns, tz=UTC],timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 41454/41454 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/41454 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 41454/41454 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| amount | float | double | 成交金额 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| count | int | double | 股票个数 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| float_mv | float | double | 流通市值 | 未单独确认；参见含义/来源定义 |  | 8048/41454 |
| float_share | float | double | 流通股票 | 未单独确认；参见含义/来源定义 |  | 19642/41454 |
| total_mv | float | double | 总市值 | 未单独确认；参见含义/来源定义 |  | 8048/41454 |
| total_share | float | double | 总股本 | 未单独确认；参见含义/来源定义 |  | 19642/41454 |
| trade_date | str | string | 未确认；不能仅凭字段名推断 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| ts_code | str | string | 市场类型 | 未单独确认；参见含义/来源定义 |  | 0/41454 |
| vol | int | double | 成交量 | 未单独确认；参见含义/来源定义 |  | 14758/41454 |

## index_daily

指数日线行情；路径 `E:\QuantData\10_canonical\index_daily`；自然键 `ts_code,trade_date`。

| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |
|---|---|---|---|---|---|---|
| _actual_announcement_date | 元数据 | timestamp[ns] | f_ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 23785538/23785538 |
| _announcement_date | 元数据 | timestamp[ns] | ann_date 解析值 | 未单独确认；参见含义/来源定义 |  | 23785538/23785538 |
| _available_at | 元数据 | timestamp[us, tz=UTC] | 本地观察时间与公告次日门禁的较晚者 UTC | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _batch_id | 元数据 | string | 关联 raw_batches.batch_id | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _event_available_at | 元数据 | timestamp[us, tz=UTC] | 白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻 | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _event_date | 元数据 | timestamp[ns] | 来源契约事件日期；宏观可能仅统计期末 | YYYYMMDD |  | 0/23785538 |
| _ingested_at | 元数据 | timestamp[us, tz=UTC] | 来源抓取/本地观察时间 UTC | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _knowledge_quality | 元数据 | string | observed_only 或历史行情重建 | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _period_date | 元数据 | timestamp[ns] | 财报/宏观统计期末 | 未单独确认；参见含义/来源定义 |  | 23785538/23785538 |
| _revision | 元数据 | string | 内容指纹和观察时间的版本指纹 | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _row_hash | 元数据 | string | 来源业务字段内容指纹；不含观察时间 | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| _transform_version | 元数据 | string | Canonical 转换版本 | 未单独确认；参见含义/来源定义 |  | 0/23785538 |
| amount | float | double | 成交额（千元） | 千元 |  | 8263446/23785538 |
| change | float | double | 涨跌点 | 未单独确认；参见含义/来源定义 |  | 40009/23785538 |
| close | float | double | 收盘点位 | 未单独确认；参见含义/来源定义 |  | 35640/23785538 |
| high | float | double | 最高点位 | 未单独确认；参见含义/来源定义 |  | 20776974/23785538 |
| low | float | double | 最低点位 | 未单独确认；参见含义/来源定义 |  | 20776974/23785538 |
| open | float | double | 开盘点位 | 未单独确认；参见含义/来源定义 |  | 20776974/23785538 |
| pct_chg | float | double | 涨跌幅（%） | % |  | 40377/23785538 |
| pre_close | float | double | 昨日收盘点 | 未单独确认；参见含义/来源定义 |  | 38858/23785538 |
| trade_date | str | string | 交易日 | 未单独确认；参见含义/来源定义 | 是 | 0/23785538 |
| ts_code | str | string | TS指数代码 | 未单独确认；参见含义/来源定义 | 是 | 0/23785538 |
| vol | float | double | 成交量（手） | 手 |  | 4496680/23785538 |

## 注册表字段

以下为实际 DuckDB DESCRIBE；业务含义以 registry/database.py DDL 和 lineage 为据，其余不作猜测。JSON payload 为元数据，不是原始金融特征。

### canonical_parts（1077188 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| endpoint | VARCHAR | YES | None |
| partition_key | VARCHAR | YES | None |
| path | VARCHAR | NO | PRI |
| rows | BIGINT | YES | None |
| content_hash | VARCHAR | YES | None |
| active | BOOLEAN | YES | None |
| created_at | TIMESTAMP WITH TIME ZONE | YES | None |

### dataset_coverage（88 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| endpoint | VARCHAR | NO | PRI |
| report | JSON | YES | None |
| checked_at | TIMESTAMP WITH TIME ZONE | YES | None |

### dataset_versions（46 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| dataset_version | VARCHAR | NO | PRI |
| manifest | JSON | YES | None |
| created_at | TIMESTAMP WITH TIME ZONE | YES | None |

### data_quality_results（206856 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| result_id | VARCHAR | NO | PRI |
| endpoint | VARCHAR | YES | None |
| task_id | VARCHAR | YES | None |
| status | VARCHAR | YES | None |
| details | JSON | YES | None |
| checked_at | TIMESTAMP WITH TIME ZONE | YES | None |

### endpoint_capabilities（88 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| endpoint | VARCHAR | NO | PRI |
| status | VARCHAR | YES | None |
| details | JSON | YES | None |
| probe_time | TIMESTAMP WITH TIME ZONE | YES | None |

### experiment_registry（0 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| id | VARCHAR | NO | PRI |
| spec | JSON | YES | None |

### factor_registry（0 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| id | VARCHAR | NO | PRI |
| spec | JSON | YES | None |

### fetch_tasks（183510 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| task_id | VARCHAR | NO | PRI |
| endpoint | VARCHAR | YES | None |
| task | JSON | YES | None |
| status | VARCHAR | YES | None |
| attempts | INTEGER | YES | None |
| updated_at | TIMESTAMP WITH TIME ZONE | YES | None |
| error_kind | VARCHAR | YES | None |
| error | VARCHAR | YES | None |
| rows | BIGINT | YES | None |
| retry_after | TIMESTAMP WITH TIME ZONE | YES | None |

### fills（0 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| id | VARCHAR | NO | PRI |
| spec | JSON | YES | None |

### ingestion_runs（42956 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| run_id | VARCHAR | NO | PRI |
| kind | VARCHAR | YES | None |
| started_at | TIMESTAMP WITH TIME ZONE | YES | None |
| finished_at | TIMESTAMP WITH TIME ZONE | YES | None |
| status | VARCHAR | YES | None |
| details | JSON | YES | None |

### live_runs（0 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| id | VARCHAR | NO | PRI |
| spec | JSON | YES | None |

### model_registry（0 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| id | VARCHAR | NO | PRI |
| spec | JSON | YES | None |

### orders（0 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| id | VARCHAR | NO | PRI |
| spec | JSON | YES | None |

### raw_batches（217467 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| batch_id | VARCHAR | NO | PRI |
| task_id | VARCHAR | YES | None |
| endpoint | VARCHAR | YES | None |
| path | VARCHAR | YES | None |
| rows | BIGINT | YES | None |
| metadata | JSON | YES | None |
| state | VARCHAR | YES | None |

### schema_registry（67 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| endpoint | VARCHAR | NO | PRI |
| schema_hash | VARCHAR | NO | PRI |
| fields | JSON | YES | None |
| observed_at | TIMESTAMP WITH TIME ZONE | YES | None |

### watermarks（58 行）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| endpoint | VARCHAR | NO | PRI |
| observed_max_date | DATE | YES | None |
| updated_at | TIMESTAMP WITH TIME ZONE | YES | None |

辅助 CSV/SQLite 全字段及 SQLite 类型见 `inventory/auxiliary_tables.json`。Qlib字段及单位见数据报告，实际文件名见 supplement.json。

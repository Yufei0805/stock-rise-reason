# 股票上涨原因分析

基于社区讨论和专业投研数据，使用 AI 分析股票近期上涨原因。

## 核心特性

- ✅ **批量分析**：5只股票一批，高效处理
- ✅ **智能去重**：7天内自动跳过已分析股票
- ✅ **时间过滤**：只分析最近15天的信息
- ✅ **多数据源**：韭研公社 + AlphaPai投研 + 搜索引擎
- ✅ **自动输出**：生成txt文件，100字以内精准分析

## 数据源（最近15天）

1. **韭研公社**：Playwright爬虫，高质量讨论
2. **AlphaPai投研**：路演纪要 + 机构点评
3. **搜索引擎**：雪球、东财、淘股吧等（Claude搜索）

## 使用方法

### 单个或多个股票
```bash
python analyzer.py 英科医疗 沃尔核材
python analyzer.py 300677 002130
```

### 从Excel读取
```bash
python analyzer.py --excel stocks.xlsx
```

## 工作流程

1. **Python爬取**：韭研公社（15天内）+ AlphaPai API（15天内）
2. **Claude搜索**：其他社区讨论（15天内）
3. **Claude分析**：整合所有数据，生成上涨原因
4. **自动保存**：输出txt文件

## 配置文件

`config.yaml`：
- `batch_size`: 批量大小（默认5）
- `output_length`: 分析字数（默认100）
- `deduplication.days`: 去重天数（默认7）
- `output.save_path`: 输出路径（默认当前目录）

## 输出示例

```
股票上涨原因分析

英科医疗 (300677)

英科医疗近期上涨主要受益于手套产品提价预期...（100字以内）
```

## 依赖安装

```bash
pip install requests beautifulsoup4 playwright pandas openpyxl pyyaml
playwright install chromium
```

## 注意事项

- 执行时间：约15-20秒/股票
- 数据时效：最近15天
- AlphaPai可选：未配置时只使用社区数据

---

⚠️ **免责声明**：本工具提供的分析基于公开信息和AI分析，仅供参考，不构成投资建议。

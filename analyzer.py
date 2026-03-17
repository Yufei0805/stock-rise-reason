#!/usr/bin/env python3
"""
Stock Rise Reason Analyzer - 股票上涨原因分析
基于社区讨论和专业投研数据，使用 AI 分析股票上涨原因
"""

import os
import sys
import json
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
import pandas as pd

# 使用本地 scraper.py
CURRENT_DIR = Path(__file__).parent
sys.path.insert(0, str(CURRENT_DIR))

# 添加 alphapai 客户端路径
ALPHAPAI_CLIENT_PATH = CURRENT_DIR.parent / 'alphapai-research' / 'alphapai-research' / 'scripts'
sys.path.insert(0, str(ALPHAPAI_CLIENT_PATH))

try:
    from alphapai_client import AlphaPaiClient, load_config
    ALPHAPAI_AVAILABLE = True
except ImportError:
    ALPHAPAI_AVAILABLE = False
    print("⚠️ AlphaPai 客户端未安装，将无法进行 AI 分析")


def parse_stocks_from_excel(excel_path):
    """从 Excel 文件读取股票列表

    支持格式：
    1. 包含"代码"或"名称"的列
    2. A列包含元组字符串：★('000525.SZ', '红太阳', '农化制品')
    """
    try:
        df = pd.read_excel(excel_path)
        df = df.dropna(how='all')

        stocks = []

        # 方式1：查找代码列和名称列
        code_col = None
        name_col = None

        for col in df.columns:
            col_str = str(col).lower()
            if '代码' in col_str and code_col is None:
                code_col = col
            elif ('名称' in col_str or '股票' in col_str) and name_col is None:
                name_col = col

        # 如果找到了标准列
        if code_col or name_col:
            for idx, row in df.iterrows():
                code = str(row[code_col]).strip() if code_col and pd.notna(row[code_col]) else None
                name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else None

                if code == 'nan':
                    code = None
                if name == 'nan':
                    name = None

                if code or name:
                    stocks.append({'code': code, 'name': name})
        else:
            # 方式2：尝试从A列解析元组格式
            first_col = df.columns[0]
            for idx, row in df.iterrows():
                value = str(row[first_col]).strip()

                if value and value != 'nan':
                    # 尝试解析元组格式：★('000525.SZ', '红太阳', '农化制品')
                    import re
                    match = re.search(r"'([^']+)'.*?'([^']+)'", value)
                    if match:
                        code_with_market = match.group(1)
                        name = match.group(2)

                        # 去掉市场后缀 .SZ 或 .SH
                        code = code_with_market.split('.')[0]

                        stocks.append({'code': code, 'name': name})

        return stocks

    except Exception as e:
        print(f"❌ 读取 Excel 文件失败：{e}")
        return []


def parse_stocks(args):
    """解析股票输入

    支持格式：
    - 空格分隔：300677 英科医疗 002130 沃尔核材
    - 逗号分隔：300677,002130
    - 混合：300677 英科医疗,002130 沃尔核材
    """
    stocks = []

    # 合并所有参数
    all_args = ' '.join(args)

    # 按逗号和空格分割
    tokens = all_args.replace(',', ' ').split()

    # 配对：代码+名称
    i = 0
    while i < len(tokens):
        token = tokens[i]

        # 判断是代码还是名称
        if token.isdigit() and len(token) == 6:
            # 是代码
            code = token
            # 下一个是名称吗？
            if i + 1 < len(tokens) and not (tokens[i+1].isdigit() and len(tokens[i+1]) == 6):
                name = tokens[i+1]
                i += 2
            else:
                name = None
                i += 1

            stocks.append({'code': code, 'name': name})
        else:
            # 是名称，需要查询代码
            stocks.append({'code': None, 'name': token})
            i += 1

    return stocks


def get_stock_name_from_code(stock_code):
    """从东方财富股吧获取股票名称"""
    try:
        import requests
        from bs4 import BeautifulSoup

        url = f"https://guba.eastmoney.com/list,{stock_code}.html"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.find('title')
            if title:
                # 标题格式通常是：股票名称(代码)股吧_xxx
                text = title.text
                match = re.search(r'(.+?)\(', text)
                if match:
                    return match.group(1).strip()
        return None
    except:
        return None


def fetch_stock_data(stock_code, stock_name):
    """调用 scraper.py 获取股票数据"""
    scraper_path = CURRENT_DIR / 'scraper.py'

    if not scraper_path.exists():
        return {'success': False, 'error': 'scraper.py 不存在'}

    try:
        # 如果没有股票名称，尝试获取
        if not stock_name or stock_name == stock_code:
            fetched_name = get_stock_name_from_code(stock_code)
            if fetched_name:
                stock_name = fetched_name

        # 直接导入 scraper 模块
        import importlib.util
        spec = importlib.util.spec_from_file_location("scraper", scraper_path)
        scraper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scraper)

        # 调用爬取函数
        results = scraper.fetch_all_platforms(stock_code, stock_name)

        # 转换为我们需要的格式
        data = {
            'success': True,
            'community': {
                'jiuyangongshe': [],
                'eastmoney': [],
                'taoguba': []
            },
            'research': {
                'roadshow': [],
                'comment': []
            }
        }

        # 提取社区数据
        for platform_name, platform_data in results.items():
            if platform_data.get('success'):
                items = platform_data.get('data', [])

                if platform_name == '韭研公社':
                    data['community']['jiuyangongshe'] = [item['title'] for item in items]
                elif platform_name == '东方财富股吧':
                    data['community']['eastmoney'] = [item['title'] for item in items]
                elif platform_name == '淘股吧':
                    data['community']['taoguba'] = [item['title'] for item in items]
                elif platform_name == '路演纪要':
                    data['research']['roadshow'] = [item.get('summary', '') for item in items if item.get('summary')]
                elif platform_name == '机构点评':
                    data['research']['comment'] = [item.get('summary', '') for item in items if item.get('summary')]

        # 返回数据和股票名称
        data['stock_name'] = stock_name
        return data

    except Exception as e:
        return {'success': False, 'error': str(e)}


def parse_scraper_output(output):
    """解析 scraper.py 的输出"""
    data = {
        'success': True,
        'community': {
            'jiuyangongshe': [],
            'eastmoney': [],
            'taoguba': []
        },
        'research': {
            'roadshow': [],
            'comment': []
        }
    }

    lines = output.split('\n')
    current_section = None
    current_platform = None

    for line in lines:
        line = line.strip()

        # 识别章节
        if '## 📱 社区讨论' in line:
            current_section = 'community'
        elif '## 📈 专业投研' in line:
            current_section = 'research'
        elif '### 韭研公社' in line:
            current_platform = 'jiuyangongshe'
        elif '### 东方财富股吧' in line:
            current_platform = 'eastmoney'
        elif '### 淘股吧' in line:
            current_platform = 'taoguba'
        elif '### 路演纪要' in line:
            current_platform = 'roadshow'
        elif '### 机构点评' in line:
            current_platform = 'comment'

        # 提取标题（以数字开头）
        if line and line[0].isdigit() and '. **' in line:
            # 提取标题
            if '**' in line:
                start = line.find('**') + 2
                end = line.find('**', start)
                if end > start:
                    title = line[start:end]

                    if current_section == 'community' and current_platform:
                        data['community'][current_platform].append(title)

        # 提取投研摘要（📝 开头）
        if line.startswith('📝'):
            summary = line[2:].strip()
            if current_section == 'research' and current_platform:
                data['research'][current_platform].append(summary)

    return data


def analyze_rise_reason(stock_code, stock_name, data, mode='flash'):
    """分析上涨原因 - 直接返回数据供 Claude 分析"""
    # 提取关键信息
    community_titles = []
    for platform, titles in data['community'].items():
        community_titles.extend(titles[:5])  # 每个平台取前5条

    research_summaries = []
    for platform, summaries in data['research'].items():
        research_summaries.extend(summaries[:5])  # 每个平台取前5条

    return {
        'community_titles': community_titles[:15],  # 最多15条
        'research_summaries': research_summaries[:15],  # 最多15条
        'stats': count_data_sources(data)
    }


def build_analysis_prompt(stock_name, data):
    """构建分析提示词"""
    prompt = f"基于以下社区讨论和专业投研数据，分析{stock_name}近期上涨的主要原因。\n\n"
    prompt += "要求：\n"
    prompt += "1. 100字以内\n"
    prompt += "2. 提取核心驱动因素（如：业绩、政策、行业、事件等）\n"
    prompt += "3. 优先引用专业投研观点\n"
    prompt += "4. 语言简洁专业\n\n"

    # 添加社区讨论标题
    prompt += "社区讨论热点：\n"
    all_titles = []
    for platform, titles in data['community'].items():
        all_titles.extend(titles[:3])  # 每个平台取前3条

    if all_titles:
        for i, title in enumerate(all_titles[:10], 1):  # 最多10条
            prompt += f"{i}. {title}\n"
    else:
        prompt += "（无相关讨论）\n"

    prompt += "\n"

    # 添加专业投研摘要
    prompt += "专业投研观点：\n"
    all_summaries = []
    for platform, summaries in data['research'].items():
        all_summaries.extend(summaries[:3])  # 每个平台取前3条

    if all_summaries:
        for i, summary in enumerate(all_summaries[:10], 1):  # 最多10条
            prompt += f"{i}. {summary}\n"
    else:
        prompt += "（无相关投研）\n"

    return prompt


def count_data_sources(data):
    """统计数据来源"""
    community_count = sum(len(titles) for titles in data['community'].values())
    research_count = sum(len(summaries) for summaries in data['research'].values())

    return {
        'community': community_count,
        'research': research_count,
        'total': community_count + research_count
    }


def generate_report(results, output_file=None):
    """生成报告 - 输出数据供 Claude 分析"""
    print("\n" + "="*80)
    print("📊 股票数据已收集，请 Claude 分析上涨原因")
    print("="*80 + "\n")

    for result in results:
        stock = result['stock']
        analysis = result['analysis']

        # 股票标题
        if stock['name']:
            print(f"## {stock['name']} ({stock['code']})")
        else:
            print(f"## {stock['code']}")
        print()

        # 数据来源统计
        stats = analysis['stats']
        print(f"**数据来源**: {stats['community']}条社区讨论 + {stats['research']}条专业投研")
        print()

        # 社区讨论标题
        if analysis['community_titles']:
            print("**社区讨论热点**:")
            for i, title in enumerate(analysis['community_titles'], 1):
                print(f"{i}. {title}")
            print()

        # 专业投研摘要
        if analysis['research_summaries']:
            print("**专业投研观点**:")
            for i, summary in enumerate(analysis['research_summaries'], 1):
                print(f"{i}. {summary}")
            print()

        print("---")
        print()

    print("\n请基于以上数据，为每只股票生成100字以内的上涨原因分析。")
    print("="*80 + "\n")

    # 返回结果供后续处理
    return results


def save_analysis_to_txt(results, analyses_dict, output_path):
    """保存分析结果为txt文件"""
    content = "股票上涨原因分析\n\n"

    for result in results:
        stock = result['stock']
        stock_key = f"{stock['name']}_{stock['code']}" if stock['name'] else stock['code']

        if stock_key in analyses_dict:
            if stock['name']:
                content += f"{stock['name']} ({stock['code']})\n\n"
            else:
                content += f"{stock['code']}\n\n"

            content += f"{analyses_dict[stock_key]}\n\n"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"✅ 分析结果已保存到：{output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="股票上涨原因分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python analyzer.py 300677 英科医疗
  python analyzer.py 300677 英科医疗 002130 沃尔核材
  python analyzer.py 300677,002130
  python analyzer.py 300677 英科医疗 --save
  python analyzer.py 300677 英科医疗 --mode think
  python analyzer.py --excel stocks.xlsx
  python analyzer.py --excel D:\\我的股票.xlsx
        """
    )

    parser.add_argument(
        'stocks',
        nargs='*',
        help='股票代码和名称（支持多个，空格或逗号分隔）'
    )

    parser.add_argument(
        '--excel',
        type=str,
        help='从 Excel 文件读取股票列表'
    )

    parser.add_argument(
        '--save',
        action='store_true',
        help='保存报告为 markdown 文件'
    )

    parser.add_argument(
        '--mode',
        choices=['flash', 'think'],
        default='flash',
        help='AI 分析模式（flash=快速，think=深度）'
    )

    args = parser.parse_args()

    # 解析股票列表
    stocks = []

    if args.excel:
        # 从 Excel 读取
        print(f"📂 从 Excel 文件读取股票列表：{args.excel}\n")
        stocks = parse_stocks_from_excel(args.excel)
    elif args.stocks:
        # 从命令行参数读取
        stocks = parse_stocks(args.stocks)
    else:
        print("❌ 请提供股票代码/名称或使用 --excel 指定 Excel 文件")
        parser.print_help()
        return

    if not stocks:
        print("❌ 未识别到有效的股票代码或名称")
        return

    print(f"📊 准备分析 {len(stocks)} 只股票...\n")

    results = []

    for i, stock in enumerate(stocks, 1):
        print(f"[{i}/{len(stocks)}] 分析 {stock.get('name') or stock.get('code')}...")

        # 1. 爬取数据
        print("  ├─ 爬取数据...")
        data = fetch_stock_data(stock['code'], stock['name'] or stock['code'])

        if not data.get('success'):
            print(f"  └─ ❌ 爬取失败：{data.get('error')}")
            continue

        # 2. AI 分析
        print(f"  ├─ AI 分析（{args.mode} 模式）...")
        analysis = analyze_rise_reason(
            stock['code'],
            stock['name'] or stock['code'],
            data,
            mode=args.mode
        )

        print(f"  └─ ✓ 完成")
        print()

        results.append({
            'stock': stock,
            'analysis': analysis
        })

    # 3. 生成报告
    if results:
        generate_report(results)

        # 提示用户：数据已收集，等待Claude分析
        print("\n" + "="*80)
        print("💡 提示：请将上述数据提供给 Claude，让其生成上涨原因分析")
        print("="*80 + "\n")
    else:
        print("❌ 没有成功分析的股票")


if __name__ == '__main__':
    main()

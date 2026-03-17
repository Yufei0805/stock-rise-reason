#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
股票社区观点爬虫
从韭研公社获取最新讨论（15天内）

过滤规则：
- 只保留主贴，过滤其他股票讨论
- 过滤晒交易单的帖子
- 过滤网站介绍等无关内容
"""

import requests
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import os
from datetime import datetime, timedelta

def is_within_days(time_str, days=30):
    """判断时间字符串是否在指定天数内"""
    if not time_str or time_str == '最近' or time_str == '-':
        # 如果没有时间或显示"最近"，认为是最新的，保留
        return True

    try:
        now = datetime.now()
        cutoff_date = now - timedelta(days=days)

        # 尝试解析不同的时间格式
        # 格式1: "2026-02-27 15:44" 或 "2026-02-27"
        if re.match(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', time_str):
            post_date = datetime.strptime(time_str.split()[0], '%Y-%m-%d')
            return post_date >= cutoff_date

        # 格式2: "03-16 09:55" (月-日 时:分，假设是当前年份)
        if re.match(r'\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}', time_str):
            month_day = time_str.split()[0]
            post_date = datetime.strptime(f"{now.year}-{month_day}", '%Y-%m-%d')
            # 如果日期在未来（跨年情况），使用去年
            if post_date > now:
                post_date = datetime.strptime(f"{now.year-1}-{month_day}", '%Y-%m-%d')
            return post_date >= cutoff_date

        # 格式3: "03-16" (月-日)
        if re.match(r'\d{1,2}[-/]\d{1,2}$', time_str):
            post_date = datetime.strptime(f"{now.year}-{time_str}", '%Y-%m-%d')
            # 如果日期在未来（跨年情况），使用去年
            if post_date > now:
                post_date = datetime.strptime(f"{now.year-1}-{time_str}", '%Y-%m-%d')
            return post_date >= cutoff_date

        # 无法解析的格式，保留
        return True
    except:
        # 解析失败，保留
        return True

# 尝试导入 alphapai 客户端（可选）
current_dir = os.path.dirname(os.path.abspath(__file__))
ALPHAPAI_AVAILABLE = False

try:
    # 尝试从环境中导入（如果已安装）
    from alphapai_client import AlphaPaiClient, load_config
    ALPHAPAI_AVAILABLE = True
except ImportError:
    # 尝试从相对路径导入（如果在 skills 目录结构中）
    try:
        alphapai_path = os.path.join(
            os.path.dirname(current_dir),
            'alphapai-research', 'alphapai-research', 'scripts'
        )
        if os.path.exists(alphapai_path):
            sys.path.insert(0, alphapai_path)
            from alphapai_client import AlphaPaiClient, load_config
            ALPHAPAI_AVAILABLE = True
    except ImportError:
        pass

def extract_relevant_summary(stock_name, content, content_type):
    """从内容中提取与股票相关的段落作为摘要"""
    if not content:
        return ''

    # 先尝试按列表项分割（如"1、"、"2、"、"18、"等）
    # 使用正则捕获分隔符，这样可以保留完整的列表项
    # 注意：只匹配换行符后或开头的数字序号，避免误匹配句子中的数字
    parts = re.split(r'((?:^|\n)\d+[、．]\s*)', content, flags=re.MULTILINE)

    # 重新组合列表项（分隔符 + 内容）
    list_items = []
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            # 组合：序号 + 内容
            item_text = parts[i] + parts[i + 1]
            list_items.append(item_text.strip())

    # 查找包含股票名的列表项
    for item in list_items:
        if stock_name in item and len(item) > 10:
            # 提取包含股票名的完整句子（到句号、分号或换行）
            # 找到股票名所在的句子
            sentences_in_item = re.split(r'([。；\n])', item)
            result_parts = []
            found_stock = False

            for j in range(0, len(sentences_in_item), 2):
                sentence = sentences_in_item[j]
                separator = sentences_in_item[j + 1] if j + 1 < len(sentences_in_item) else ''

                if stock_name in sentence:
                    found_stock = True
                    result_parts.append(sentence + separator)
                    # 继续添加后续1-2句以提供上下文
                    for k in range(j + 2, min(j + 6, len(sentences_in_item)), 2):
                        next_sentence = sentences_in_item[k]
                        next_separator = sentences_in_item[k + 1] if k + 1 < len(sentences_in_item) else ''
                        result_parts.append(next_sentence + next_separator)
                    break

            if found_stock and result_parts:
                summary = ''.join(result_parts).strip()
                # 去掉开头的序号（如"18、"）
                summary = re.sub(r'^\d+[、．]\s*', '', summary)
                # 限制长度，但保证完整性
                if len(summary) > 300:
                    # 在300字附近找最近的句号
                    truncate_pos = summary.rfind('。', 200, 320)
                    if truncate_pos > 0:
                        return summary[:truncate_pos + 1]
                    return summary[:300] + '...'
                return summary

    # 如果没有列表格式，按句子分割（中文句号、问号、感叹号）
    # 使用捕获组保留分隔符
    parts = re.split(r'([。！？])', content)

    # 重新组合句子（内容 + 标点）
    sentences = []
    for i in range(0, len(parts) - 1, 2):
        sentence = parts[i] + (parts[i + 1] if i + 1 < len(parts) else '')
        sentence = sentence.strip()
        if sentence:
            sentences.append(sentence)

    # 查找包含股票名的句子
    relevant_sentences = []
    for idx, sentence in enumerate(sentences):
        if stock_name in sentence and len(sentence) > 10:
            # 过滤掉以标点或数字开头的不完整句子
            if re.match(r'^[、，。；：\d%]', sentence):
                continue

            # 检查是否是纯股票列表（大量顿号，且股票名前后都是顿号）
            # 这种情况下，如果股票名不在句子开头附近，就跳过
            stock_pos = sentence.find(stock_name)
            if '、' in sentence and stock_pos > 50:
                # 检查股票名前后是否都是顿号分隔的列表
                before_stock = sentence[:stock_pos]
                after_stock = sentence[stock_pos + len(stock_name):]
                # 如果前后都有多个顿号，说明是纯列表，跳过
                if before_stock.count('、') >= 3 and after_stock.count('、') >= 2:
                    continue

            # 检查是否是股票列表（包含多个顿号分隔的股票名）
            # 如果是列表且股票名在中间，需要找到列表开头
            if '、' in sentence and sentence.index(stock_name) > 10:
                # 尝试从前一句开始，找到列表的开头
                if idx > 0:
                    prev_sentence = sentences[idx - 1]
                    # 如果前一句也包含顿号，说明是列表的一部分
                    if '、' in prev_sentence or any(keyword in prev_sentence for keyword in ['建议关注', '推荐', '重点关注', '关注']):
                        # 从前一句开始
                        combined = prev_sentence + sentence
                        # 找到包含股票名的完整部分
                        if stock_name in combined:
                            relevant_sentences.append(combined)
                            if len(relevant_sentences) >= 2:
                                break
                            continue

            relevant_sentences.append(sentence)
            # 最多取3句
            if len(relevant_sentences) >= 3:
                break

    # 如果找到相关句子，返回
    if relevant_sentences:
        summary = ''.join(relevant_sentences)
        # 限制长度，但保证完整性
        if len(summary) > 300:
            # 在300字附近找最近的句号
            truncate_pos = summary.rfind('。', 200, 320)
            if truncate_pos > 0:
                return summary[:truncate_pos + 1]
            return summary[:300] + '...'
        return summary

    # 如果没找到包含股票名的内容，返回空字符串（不显示无关摘要）
    return ''


def fetch_alphapai_roadshow(stock_name):
    """获取路演纪要（最近1个月）"""
    if not ALPHAPAI_AVAILABLE:
        return {'success': False, 'error': 'AlphaPai 客户端未安装'}

    try:
        config = load_config()
        if not config:
            return {'success': False, 'error': 'AlphaPai 配置未找到'}

        client = AlphaPaiClient(config)

        # 计算1个月前的日期
        end_time = datetime.now().strftime('%Y-%m-%d')
        start_time = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')

        # 调用 recall_data 获取路演纪要
        result = client.recall_data(
            query=stock_name,
            is_cut_off=True,
            recall_type=['roadShow', 'roadShow_ir'],
            start_time=start_time,
            end_time=end_time
        )

        if result.get('code') == 200000:
            items = result.get('data', [])
            formatted_items = []
            seen_base_ids = set()  # 用于去重（基础数字ID）

            for item in items:
                item_id = item.get('id', '')

                # 提取基础数字ID（去掉前缀和_es_后缀）
                base_id = item_id
                # 去掉_es_后缀
                base_id = base_id.split('_es_')[0] if '_es_' in base_id else base_id
                # 提取数字部分（去掉TRANSMT、TRANSAI等前缀）
                import re
                match = re.search(r'\d+', base_id)
                if match:
                    numeric_id = match.group()
                else:
                    numeric_id = base_id

                # 跳过重复的数字ID
                if numeric_id in seen_base_ids:
                    continue

                # 跳过TRANSAI前缀的（优先保留TRANSMT）
                if item_id.startswith('TRANSAI'):
                    # 检查是否已经有TRANSMT版本
                    if numeric_id in seen_base_ids:
                        continue
                    # 如果还没有TRANSMT版本，也跳过TRANSAI（因为可能后面会有TRANSMT）
                    # 但为了不漏掉，我们先标记，如果后续没有TRANSMT就用TRANSAI
                    # 简化处理：直接跳过TRANSAI
                    continue

                seen_base_ids.add(numeric_id)

                # 提取内容 - 选择包含股票名最多的chunk
                chunks = item.get('chunks', [])
                content = ''
                max_count = 0
                for chunk in chunks:
                    count = chunk.count(stock_name)
                    if count > max_count:
                        max_count = count
                        content = chunk
                # 如果没有找到包含股票名的chunk，使用第一个chunk
                if not content and chunks:
                    content = chunks[0]

                # 提取与股票相关的摘要
                summary = extract_relevant_summary(stock_name, content, '路演纪要')

                # 如果摘要为空或不包含股票名，跳过这条（说明内容不相关）
                if not summary or stock_name not in summary:
                    continue

                formatted_items.append({
                    'title': item.get('title', ''),
                    'time': item.get('time', ''),
                    'link': f"AlphaPai 路演纪要 ID: {item_id}",
                    'type': '路演纪要',
                    'id': item_id,
                    'summary': summary
                })

                # 只取前5条不重复的
                if len(formatted_items) >= 5:
                    break

            return {'success': True, 'data': formatted_items}
        else:
            return {'success': False, 'error': '未找到路演纪要'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def fetch_alphapai_comments(stock_name):
    """获取机构点评（最近1个月）"""
    if not ALPHAPAI_AVAILABLE:
        return {'success': False, 'error': 'AlphaPai 客户端未安装'}

    try:
        config = load_config()
        if not config:
            return {'success': False, 'error': 'AlphaPai 配置未找到'}

        client = AlphaPaiClient(config)

        # 计算1个月前的日期
        end_time = datetime.now().strftime('%Y-%m-%d')
        start_time = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')

        # 调用 recall_data 获取机构点评
        result = client.recall_data(
            query=stock_name,
            is_cut_off=True,
            recall_type=['comment'],
            start_time=start_time,
            end_time=end_time
        )

        if result.get('code') == 200000:
            items = result.get('data', [])
            formatted_items = []
            seen_base_ids = set()  # 用于去重（基础数字ID）

            for item in items:
                item_id = item.get('id', '')

                # 提取基础数字ID（去掉前缀和_es_后缀）
                base_id = item_id
                # 去掉_es_后缀
                base_id = base_id.split('_es_')[0] if '_es_' in base_id else base_id
                # 提取数字部分
                import re
                match = re.search(r'\d+', base_id)
                if match:
                    numeric_id = match.group()
                else:
                    numeric_id = base_id

                # 跳过重复的数字ID
                if numeric_id in seen_base_ids:
                    continue

                seen_base_ids.add(numeric_id)

                # 提取内容 - 选择包含股票名最多的chunk
                chunks = item.get('chunks', [])
                content = ''
                max_count = 0
                for chunk in chunks:
                    count = chunk.count(stock_name)
                    if count > max_count:
                        max_count = count
                        content = chunk
                # 如果没有找到包含股票名的chunk，使用第一个chunk
                if not content and chunks:
                    content = chunks[0]

                # 提取与股票相关的摘要
                summary = extract_relevant_summary(stock_name, content, '机构点评')

                # 如果摘要为空或不包含股票名，跳过这条（说明内容不相关）
                if not summary or stock_name not in summary:
                    continue

                formatted_items.append({
                    'title': item.get('title', ''),
                    'time': item.get('time', ''),
                    'link': f"AlphaPai 机构点评 ID: {item_id}",
                    'type': '机构点评',
                    'id': item_id,
                    'institution': item.get('institution', ''),
                    'summary': summary
                })

                # 只取前5条不重复的
                if len(formatted_items) >= 5:
                    break

            return {'success': True, 'data': formatted_items}
        else:
            return {'success': False, 'error': '未找到机构点评'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def fetch_alphapai_wechat(stock_name, comment_ids):
    """获取公众号文章（最近1个月，去重）"""
    if not ALPHAPAI_AVAILABLE:
        return {'success': False, 'error': 'AlphaPai 客户端未安装'}

    try:
        config = load_config()
        if not config:
            return {'success': False, 'error': 'AlphaPai 配置未找到'}

        client = AlphaPaiClient(config)

        # 计算1个月前的日期
        end_time = datetime.now().strftime('%Y-%m-%d')
        start_time = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')

        # 调用 recall_data 获取公众号文章
        result = client.recall_data(
            query=stock_name,
            is_cut_off=True,
            recall_type=['wechat_public_article'],
            start_time=start_time,
            end_time=end_time
        )

        if result.get('code') == 200000:
            items = result.get('data', [])
            formatted_items = []

            # 去重：过滤掉与机构点评ID重复的文章
            for item in items:
                item_id = item.get('id', '')
                if item_id not in comment_ids:
                    # 提取内容
                    chunks = item.get('chunks', [])
                    content = chunks[0] if chunks and len(chunks) > 0 else ''

                    # 提取与股票相关的摘要
                    summary = extract_relevant_summary(stock_name, content, '公众号文章')

                    formatted_items.append({
                        'title': item.get('title', ''),
                        'time': item.get('time', ''),
                        'link': f"AlphaPai 公众号文章 ID: {item_id}",
                        'type': '公众号文章',
                        'id': item_id,
                        'summary': summary
                    })

                    if len(formatted_items) >= 5:  # 只取前5条
                        break

            return {'success': True, 'data': formatted_items}
        else:
            return {'success': False, 'error': '未找到公众号文章'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def scrape_jiuyangongshe(stock_name):
    """爬取韭研公社 - 使用Playwright"""
    try:
        from playwright.sync_api import sync_playwright
        import urllib.parse
    except ImportError:
        return {'success': False, 'error': 'Playwright未安装，请运行: pip install playwright && playwright install chromium'}

    encoded_name = urllib.parse.quote(stock_name)
    # 使用新的搜索URL格式
    url = f"https://www.jiuyangongshe.com/search/new?k={encoded_name}"

    try:
        with sync_playwright() as p:
            # 启动浏览器（无头模式）
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            # 访问页面
            page.goto(url, wait_until='domcontentloaded', timeout=30000)

            # 等待内容加载
            try:
                page.wait_for_selector('div.articleTypeTopR', timeout=15000)
            except:
                pass  # 超时也继续尝试

            import time
            time.sleep(3)  # 额外等待确保JS渲染完成

            # 查找文章容器
            articles = page.query_selector_all('div.articleTypeTopR')

            if not articles:
                browser.close()
                return {'success': False, 'error': '未找到相关讨论'}

            # 分两组：包含股票名的文章 和 其他文章
            priority_results = []  # 包含股票名的文章
            other_results = []     # 其他文章

            for article in articles:
                # 提取标题
                title = article.inner_text().strip()

                # 检查是否为置顶帖
                is_pinned = page.evaluate('''(element) => {
                    const parent = element.parentElement;
                    if (parent) {
                        const prevSibling = parent.querySelector('.articleTypeTop');
                        if (prevSibling && prevSibling.innerText.includes('置顶')) {
                            return true;
                        }
                    }
                    return false;
                }''', article)

                # 过滤置顶帖和官方帖
                if is_pinned or '【官方' in title or '长韭杯' in title or '清朗' in title or '涨停简图' in title or '明日看好方向投票' in title:
                    continue

                # 过滤通用复盘文章（不包含股票名的复盘）
                if '复盘' in title and stock_name not in title:
                    continue

                # 过滤明确提到其他股票的文章
                # 匹配模式：【股票名】、股票名：、股票名（、之:股票名、之：股票名
                import re
                skip_article = False
                single_stock_patterns = [
                    r'【([\u4e00-\u9fa5]{2,6})】',      # 【股票名】
                    r'([\u4e00-\u9fa5]{2,6})[：（]',    # 股票名： 或 股票名（
                    r'之[：:]([\u4e00-\u9fa5]{2,6})',   # 之:股票名 或 之：股票名
                ]

                for pattern in single_stock_patterns:
                    for match in re.finditer(pattern, title):
                        stock_in_title = match.group(1)
                        # 如果提到的股票不是目标股票，跳过这篇文章
                        if stock_in_title != stock_name:
                            skip_article = True
                            break
                    if skip_article:
                        break

                if skip_article:
                    continue

                # 查找链接 - 优先查找文章链接（/a/开头），而不是用户主页链接（/u/开头）
                link_elem = page.evaluate('''(element) => {
                    // 首先尝试在当前元素及其父元素中查找所有链接
                    let parent = element.parentElement;
                    let attempts = 0;
                    while (parent && attempts < 5) {
                        const links = parent.querySelectorAll('a');
                        // 优先查找文章链接（/a/开头）
                        for (const link of links) {
                            if (link.href && link.href.includes('/a/')) {
                                return link.href;
                            }
                        }
                        parent = parent.parentElement;
                        attempts++;
                    }

                    // 如果没找到文章链接，再查找任何链接（但排除用户主页链接）
                    parent = element.parentElement;
                    attempts = 0;
                    while (parent && attempts < 5) {
                        const links = parent.querySelectorAll('a');
                        for (const link of links) {
                            if (link.href && !link.href.includes('/u/')) {
                                return link.href;
                            }
                        }
                        parent = parent.parentElement;
                        attempts++;
                    }

                    return null;
                }''', article)

                # 跳过没有找到链接的文章
                if not link_elem:
                    continue

                # 访问文章详情页获取发布时间
                try:
                    detail_page = context.new_page()
                    detail_page.goto(link_elem, wait_until='domcontentloaded', timeout=10000)
                    time.sleep(1)

                    # 提取时间
                    time_elem = detail_page.query_selector('[class*="date"]')
                    if time_elem:
                        time_text = time_elem.inner_text().strip().split()[0]  # 只取日期部分
                    else:
                        time_text = '最近'

                    detail_page.close()

                    # 过滤15天内的文章
                    if not is_within_days(time_text, days=15):
                        continue

                except:
                    # 如果获取时间失败，跳过这篇文章
                    continue

                item = {
                    'title': title,
                    'time': time_text,
                    'link': link_elem
                }

                # 根据是否包含股票名（或简称）分组
                is_relevant = False

                # 1. 完整股票名匹配
                if stock_name in title:
                    is_relevant = True
                # 2. 对于4字股票名，前2字也算相关
                elif len(stock_name) == 4 and stock_name[:2] in title:
                    is_relevant = True
                # 3. 对于4字股票名，后2字也算相关（如"茅台"代表"贵州茅台"）
                elif len(stock_name) == 4 and stock_name[2:] in title:
                    is_relevant = True

                if is_relevant:
                    priority_results.append(item)
                else:
                    other_results.append(item)

            # 优先使用包含股票名（或简称）的文章，不够再补充其他文章
            results = priority_results[:6]
            if len(results) < 6:
                results.extend(other_results[:6 - len(results)])

            browser.close()

            if results:
                return {'success': True, 'data': results}
            else:
                return {'success': False, 'error': '未找到相关讨论'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def fetch_all_platforms(stock_code, stock_name):
    """并行获取所有平台数据（韭研公社 + AlphaPai投研）"""
    results = {
        '韭研公社': None,
        '路演纪要': None,
        '机构点评': None
    }

    # 并行获取所有数据源
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(scrape_jiuyangongshe, stock_name): '韭研公社',
            executor.submit(fetch_alphapai_roadshow, stock_name): '路演纪要',
            executor.submit(fetch_alphapai_comments, stock_name): '机构点评'
        }

        for future in as_completed(futures):
            platform = futures[future]
            try:
                result = future.result()
                results[platform] = result
            except Exception as e:
                results[platform] = {'success': False, 'error': str(e)}

    return results

---
name: trade-assistant
description: |
  Managed Agents上のTrade Assistantにクエリを送信し、結果を表示するスキル。
  10のトレードスキル（FTD検出、VCPスクリーニング、CANSLIM、マクロレジーム、
  シナリオ分析、テーマ検出、市場ブレッス、決算/経済カレンダー、
  ブレイクアウトトレードプランナー）を活用した包括的な市場分析が可能。
  トリガー: /trade-assistant, トレード分析, 市場分析依頼, 週次レビュー
---

# Trade Assistant (Managed Agents)

## Overview

クラウド上のManaged Agentsで動作するTrade Assistantに問い合わせを行うスキル。
ローカルのClaude Codeから呼び出し、結果をターミナルに表示する。

## When to Use

- 市場の総合分析を依頼したいとき
- 特定のスキル（FTD、VCP、CANSLIM等）をクラウドで実行したいとき
- 週次トレード戦略の策定時
- ニュースヘッドラインのシナリオ分析を依頼したいとき

## Usage

```
/trade-assistant 今週のマーケット見通しを教えて
/trade-assistant /ftd-detector を実行して
/trade-assistant /vcp-screener でブレイクアウト候補を探して
/trade-assistant /scenario-analyzer "Fed cuts rates by 25bp"
```

## Workflow

### Step 1: スクリプト実行

ユーザーのクエリを引数として、以下のスクリプトを実行する：

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
python scripts/query_agent.py "ユーザーのクエリ"
```

引数なしの場合はユーザーに入力を求める。

### Step 2: 結果表示

スクリプトの出力をそのままユーザーに表示する。
レポートファイルが生成された場合はパスを案内する。

## Available Sub-Skills

エージェントに以下のコマンドを送ることで特定のスキルを実行できる：

| コマンド | 機能 |
|---------|------|
| `/ftd-detector` | FTD（フォロースルーデイ）検出 |
| `/vcp-screener` | VCPブレイクアウト候補スキャン |
| `/canslim` | CANSLIM成長株スクリーニング |
| `/macro-regime` | マクロレジーム（構造転換）検出 |
| `/scenario-analyzer "headline"` | ニュースシナリオ分析（18ヶ月） |
| `/theme-detector` | 市場テーマ・セクターローテーション検出 |
| `/breadth` | 市場ブレッス（参加率）分析 |
| `/earnings` | 今週の決算カレンダー |
| `/econ-calendar` | 経済イベントカレンダー |
| `/breakout-plan` | エントリー/リスク計算付きトレードプラン |

## Notes

- APIキー（ANTHROPIC_API_KEY, FMP_API_KEY）は `.env` から自動読み込み
- エージェントとセッションはスクリプト内で自動管理
- 結果は `reports/` ディレクトリにも保存される場合がある

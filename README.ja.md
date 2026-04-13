# Trade Assistant

[English README](README.md)

**[Claude Managed Agents](https://docs.anthropic.com/en/docs/agents-and-tools/managed-agents) を使った AI エージェント構築のサンプルプロジェクトです。** Anthropic が提供するクラウドホスト型エージェントランタイム（コード実行・Web アクセス・ファイル管理を内蔵）を活用し、Streamlit チャット UI + 10 種類のトレーディング分析スキルを組み合わせた実用的なリファレンス実装です。トレーディングはあくまで題材の一例 — Skills / Agent / Environment / Session の接続パターンを学び、自分のプロジェクトの出発点としてお使いください。

> **Disclaimer**: 本ツールは教育目的の分析ツールです。投資助言ではありません。

> **Note**: Managed Agents API はベータ版です。API の `agent_toolset_20260401` や `betas=["skills-2025-10-02"]` は変更される可能性があります。

## Features

| Command | Skill | Description |
|---------|-------|-------------|
| `/scenario-analyzer "headline"` | Scenario Analyzer | ニュースヘッドラインから 18 ヶ月シナリオを構築 |
| `/ftd-detector` | FTD Detector | Follow-Through Day による市場底入れ確認 |
| `/vcp-screener` | VCP Screener | Minervini 式 Volatility Contraction Pattern スキャン |
| `/macro-regime` | Macro Regime Detector | クロスアセット比率によるマクロレジーム検出 |
| `/canslim` | CANSLIM Screener | O'Neil 式 CANSLIM 成長株スクリーニング |
| `/theme-detector` | Theme Detector | 市場テーマ・セクターローテーション分析 |
| `/breadth` | Market Breadth Analyzer | 市場参加率・ブレッス指標による健全性チェック |
| `/earnings` | Earnings Calendar | 今週の決算発表カレンダー取得 |
| `/econ-calendar` | Economic Calendar | FOMC・CPI・雇用統計などの経済イベント取得 |
| `/breakout-plan` | Breakout Trade Planner | VCP 候補からエントリー/リスク計算付きトレードプラン生成 |

## Architecture

```
Streamlit UI (app.py)
  ├── agent/client.py      — Managed Agents API ラッパー (Agent/Environment/Session 管理)
  ├── agent/sanitizer.py   — APIキー・システムパスの出力サニタイズ
  ├── config/settings.py   — 環境変数ベースの設定管理
  └── skills/
       ├── registry.py     — スキルコマンド検出 & システムプロンプト構築
       ├── scenario-analyzer/
       ├── ftd-detector/
       ├── vcp-screener/
       ├── macro-regime-detector/
       ├── canslim-screener/
       ├── theme-detector/
       ├── market-breadth-analyzer/
       ├── earnings-calendar/
       ├── economic-calendar-fetcher/
       └── breakout-trade-planner/
```

各スキルは `SKILL.md`（エージェント向け指示）、`references/`（分析手法ドキュメント）、`scripts/`（Python スクリプト + テスト）で構成されています。

## Learning Guide — Managed Agents API

トレーディングのドメイン知識を無視して、**Managed Agents API の使い方**を学ぶには以下の 3 ファイルを順に読んでください。

### 1. `bootstrap.py` — リソース登録の流れ

Managed Agents には 3 つの主要リソースがあります:

| リソース | 役割 | ライフサイクル |
|----------|------|---------------|
| **Skill** | エージェントが使える専門スクリプト群 | `skills.create()` で登録、Agent に紐付け |
| **Agent** | モデル + システムプロンプト + スキル | `agents.create()` で作成、再利用可能 |
| **Environment** | コード実行用クラウドサンドボックス | `environments.create()` で作成、再利用可能 |

`bootstrap.py` はこの 3 つを順に作成し、ID を `.env` に保存します。

### 2. `agent/client.py` — セッションとストリーミング

Agent + Environment が揃ったら **Session** を作成してチャットします:

```
Session = Agent + Environment の実行インスタンス
  → events.stream() で SSE 接続
  → events.send() でユーザーメッセージ送信
  → agent.message / agent.tool_use / session.status_idle イベントを受信
```

`ManagedAgentClient` クラスの `send_message_streaming()` がこのパターンの実装です。

### 3. `skills/registry.py` — スキルルーティングパターン

ユーザー入力からスキルを検出し、エージェントのシステムプロンプトを動的に拡張するパターンです。`detect_skill()` がコマンド (`/vcp-screener`) やキーワード (`VCPブレイクアウト`) にマッチすると、対応する `SKILL.md` と `references/` を読み込んでプロンプトに注入します。

### なぜ2つのスキル機構があるのか？

本プロジェクトは **API Skills**（サンドボックスへのファイル配信）と **ローカル registry**（プロンプト注入）を併用しています。API Skills はスクリプトをクラウド環境に配置し、ローカル registry はシステムプロンプトを拡張してエージェントに分析手法を指示します。詳細は `CLAUDE.md` を参照してください。

## Prerequisites

- Python 3.12+
- [Anthropic API Key](https://console.anthropic.com/) (Managed Agents API アクセス付き)
- [FMP API Key](https://financialmodelingprep.com/) (ファンダメンタル/価格データ用)

## Setup

```bash
# Clone
git clone https://github.com/<your-username>/claude-trading-agent.git
cd claude-trading-agent

# Virtual environment
python -m venv .venv
source .venv/bin/activate

# Dependencies
pip install -e .

# Environment variables
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY, FMP_API_KEY

# Register skills, agent, and environment with Managed Agents API
python bootstrap.py
```

`bootstrap.py` は以下を自動実行し、取得した ID を `.env` に書き込みます:

1. 10 スキルを Skills API に登録
2. Agent を作成（スキル紐付け + システムプロンプト設定）
3. Environment を作成（クラウドサンドボックス）

既に ID が `.env` にある場合はスキップされます。強制再作成は `python bootstrap.py --force` で実行できます。

## Usage

### Streamlit UI

```bash
streamlit run app.py
```

ブラウザで `http://localhost:8501` を開き、チャットでスキルコマンドを入力します。

### CLI

```bash
python scripts/query_agent.py "今週のマーケット見通しを教えて"
python scripts/query_agent.py "/vcp-screener"
python scripts/query_agent.py  # interactive mode
```

CLI は Streamlit UI と同じ Agent/Environment/スキルルーティングを使用します。

### Docker

```bash
docker compose up --build
```

## Testing

各スキルにはユニットテストが含まれています。スキル間のテスト名衝突を避けるため、スキル単位で実行してください:

```bash
# dev 依存のインストール (pytest 含む)
pip install -r requirements-dev.txt

# スキル単位でテスト実行
python -m pytest skills/vcp-screener/scripts/tests/ -v
python -m pytest skills/ftd-detector/scripts/tests/ -v
```

## Configuration

主要な環境変数は `.env.example` を参照してください。

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API キー |
| `FMP_API_KEY` | No | Financial Modeling Prep API キー |
| `CLAUDE_MODEL` | No | 使用モデル (default: `claude-sonnet-4-6`) |
| `MANAGED_AGENT_ID` | No | 既存 Agent ID (`bootstrap.py` が自動設定) |
| `MANAGED_ENVIRONMENT_ID` | No | 既存 Environment ID (`bootstrap.py` が自動設定) |
| `APP_LOCALE` | No | UI 言語 `ja` / `en` (default: `ja`) |

## License

MIT

# Trade Assistant — Claude Managed Agents Reference Implementation

## Overview

Anthropic の Managed Agents API を使ったチャットアプリのリファレンス実装。
10 種類のトレーディング分析スキルを搭載し、Streamlit UI / CLI / Docker で動作する。

## Architecture

```
app.py (Streamlit UI)
  → skills/registry.py    ユーザー入力からスキルを検出
  → agent/client.py       Managed Agents API 呼び出し (Agent/Session/Event)
  → agent/sanitizer.py    出力からAPIキー・パスをリダクション
  → config/settings.py    .env ベースの設定管理
```

**設計意図**: UI → ルーティング → API → セキュリティの4層分離。
スキルのドメインロジック (`skills/*/scripts/`) はフレー���ワークから完全に独立している。

## Development Workflow

```bash
# Initial setup (one-time)
cp .env.example .env           # Set ANTHROPIC_API_KEY, FMP_API_KEY
pip install -r requirements.txt
python bootstrap.py            # Register Skills → Agent → Environment

# Run
streamlit run app.py           # Web UI
python scripts/query_agent.py  # CLI

# Test
python -m pytest skills/ -v
```

## Key Files

| File | Purpose |
|------|---------|
| `bootstrap.py` | ワンコマンドプロビジョニング (Skills/Agent/Environment 登録) |
| `agent/client.py` | Managed Agents API ラッパー — セッション管理とSSEストリーミング |
| `skills/registry.py` | スキルコマンド検出とシステムプロンプト動的構築 |
| `config/settings.py` | 全設定の一元管理 (.env → Python 定数) |
| `agent/sanitizer.py` | APIキー・絶対パスのハードコード型リダクション |

## Skill Structure

各スキルは以下の構造:

```
skills/<skill-name>/
  ├── SKILL.md          # エージ���ント向けの実行指示
  ├── references/       # 分析手法のリファレンスドキュメント
  └── scripts/
      ├── *.py          # ビジネスロジック
      └── tests/        # ユニットテスト
```

## Known Limitations

1. **スキル呼び出し毎に新��い Agent を作成**: `_create_skill_session()` がスキルトリガーの度に `agents.create()` を実行する。コスト・レイテンシの観点でキャッシュ/再利用パターンに改善余地あり。

2. **FMP_API_KEY のシステムプロンプト埋め込��**: `agent/client.py` の `_build_system_prompt()` で API キーを平文でプロンプトに書き込んでいる���Managed Agents の Environment Variables / Secrets 機能が利用可能になれば移行すべき。

3. **Managed Agents API はベータ版**: `agent_toolset_20260401`、`betas=["skills-2025-10-02"]` 等の識別子は変更される可能性がある。

## Conventions

- テストは各スキルの `scripts/tests/` に配置
- コメントは英語、UI テキストは日英対応 (`APP_LOCALE`)
- 生成レポートは `reports/` に保存（.gitignore 対象）

# CLAUDE.md

## プロジェクト概要
Google Workspace（Calendar / Gmail / Drive）の過去7日間のデータを取得し、
Vertex AI (Gemini) で週次レポートを生成して Gmail の下書きに保存する Python スクリプト。

GCP プロジェクト: `weekly-report-gen-489402`

## ディレクトリ構成
```
workspace-digest/
├── auth.py          # 初回OAuth認証 → token.json を生成
├── main.py          # メインスクリプト（データ取得 → AI要約 → Gmail下書き）
├── credentials.json # GCP OAuth クライアント（gitignore済み）
├── token.json       # 認証トークン（auth.py実行後に生成、gitignore済み）
├── .env             # 環境変数（gitignore済み）
└── requirements.txt
```

## セットアップ手順
1. `pip install -r requirements.txt`
2. `python auth.py` → ブラウザで認証 → token.json 生成
3. `python main.py` → 週次レポート生成 → Gmail下書きに保存

## 開発ルール
- コード変更後は自動でコミット＆プッシュまで行う
- APIキーは `.env` に記載し、ソースコードに直接書かない
- `credentials.json` / `token.json` は絶対にコミットしない

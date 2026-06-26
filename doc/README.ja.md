# NodeRC

![Screenshot](images/screenshot.png)

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRCは、PyQt5を使用したPythonで書かれたビジュアルノードベースのエディタです。このプロジェクトでは、インタラクティブなキャンバス上でノードを作成、接続、管理でき、ビジュアルプログラミングやロジックグラフの構築に使いやすいインターフェイスを提供します。

## 特徴
- **インタラクティブキャンバス:** パンとズームをサポートする無限のワークスペース。
- **ノードアーキテクチャ:** 着信および発信接続（ソケット）をサポートするさまざまなタイプのノード。
- **動的接続:** 実行ポートとデータポートの視覚的なリンク。
- **構成システム:** 集中構成ファイルを介した色、サイズ、スタイルのカスタマイズ。
- **検索メニュー:** キャンバスに新しいノードをすばやく追加するための便利なメニュー。

## 要件
- Python 3.7+
- PyQt5

## インストール

1. リポジトリのクローン:
   ```bash
   git clone <リポジトリのURL>
   cd nodeRC
   ```

2. 依存関係のインストール:
   ```bash
   pip install -r requirements.txt
   ```

## 使用方法
エディタを起動するには、以下を実行します:
```bash
python nodeRC.py
```

## プロジェクト構造
- `nodeRC.py` - メインエントリポイント。
- `canvas.py` - インタラクティブなキャンバスロジックとグラフ管理。
- `nodes.py` - ノードとソケットの基本クラスおよび特化クラス。
- `configuration.py` - 設定ファイル（色、スタイル、UIパラメータ）。
- `search_menu.py` - ノードを検索して追加するためのダイアログ。
- `diagnostics.py` - ロギングと例外処理。
- `rc_documentation_extractor.py` - コマンドドキュメントを抽出するためのユーティリティ。

## ライセンス
このプロジェクトは「現状有姿」で配布されています。詳細についてはプロジェクトファイルを参照してください。

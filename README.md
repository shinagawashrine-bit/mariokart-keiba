# マリカー競馬

友達同士でマリオカートにチップを賭ける、競馬風のWebアプリ。

- 投票用（みんなに配る）：https://shinagawashrine-bit.github.io/mariokart-keiba/#bet
- 大画面用（オッズ画面）：https://shinagawashrine-bit.github.io/mariokart-keiba/#board
- 管理用（主催者専用・暗証番号あり）：https://shinagawashrine-bit.github.io/mariokart-keiba/#admin
- 成績表：https://shinagawashrine-bit.github.io/mariokart-keiba/#stats

## 仕組み
- ページは GitHub Pages、データは Firebase（Firestore）。アカウントなしでURLを開くだけで使える。
- `config.js`：Firebase の設定と管理画面の暗証番号。
- `firestore.rules`：Firestore に貼るルール。
- アプリ本体の元ファイルと設計資料は https://github.com/shinagawashrine-bit/questions/tree/main/mariokart-keiba にある。`index.html` はそこから `web/build.py` で作ったもの。

## 開発・動作確認

このリポジトリは静的ファイルなので、依存パッケージのインストールやビルドは不要。

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

通常起動すると `config.js` の共有 Firebase に接続する。動作確認で本番データを変更しないこと。

書き込み処理の回帰テストは、Node.js の標準機能だけで実行できる。

```sh
node tests/writes.test.cjs
```

画面操作のテストは Python の Playwright と `/usr/bin/chromium` がある環境で実行する。

```sh
python3 tests/browser_smoke.py
```

両テストはローカルの Firestore テストダブルを使用する。画面操作テストは外部リクエストを差し替えるため、本番の Firebase には接続しない。実際の Firestore SDK・権限ルール・ネットワークの結合検証は別途必要。

書き込みは Firestore のトランザクションで最新の文書を更新し、投票・取消の成功通知は保存完了後に表示する。結果確定と取消ではレース状態・履歴を一括保存する。変更を再生成で失わないよう、`index.html` の修正は元ソースにも反映してから `web/build.py` を実行すること。

管理者認証は引き続きブラウザー内の PIN 判定であり、本人確認やアクセス制限を保証しない。公開運用に向けた認証の導入には Firebase Authentication の設定と Firestore ルールの同時更新が必要。また、残高・購入上限の検証は他の投票文書について端末の同期済みデータを使うため、複数の投票文書をまたぐ同一参加者の同時購入を完全には防がない。これらはサーバー側での受付検証を含めて対応する必要がある。


## 管理画面

最初のシステムの配色・ボタン・パネルを維持し、「準備」「開催中」「終了後」の切り替えを追加している。開催中は元のレース進行・出走表・代理入力を表示し、チップ調整とURLは必要なときに開く。スマホの投票画面は従来の配置を維持している。

終了後の最終チップ表を閉じても当日のデータは残る。初期化は「終了後」→「次の開催を準備」から明示的に行う。CSV保存が失敗した場合、「保存して終了」は大会を終了しない。

管理画面のデスクトップ・モバイル画像をテストデータで撮影する場合：

```sh
KEIBA_SCREENSHOT_DIR=/tmp/mariokart-admin-screenshots python3 tests/browser_smoke.py
```

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

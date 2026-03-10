# Poke-Controller-Modified-Extension カスタムコマンド集

[Poke-Controller-Modified-Extension](https://github.com/futo030/Poke-Controller-Modified-Extension)用の自作自動化コマンドです。

## Discord通知の設定

自動化コマンドの実行状況（色違い出現、周回数、エラー等）をDiscordに通知できます。

### 1. Discord Webhook URLを取得する

1. Discordで通知を受け取りたいサーバーのチャンネルを開く
2. チャンネル編集 > 連携サービス > ウェブフック を開く
3. 「新しいウェブフック」を作成し、「ウェブフックURLをコピー」をクリック

### 2. `.env`ファイルを設定する

`SerialController/` ディレクトリに `.env` ファイルを作成し、取得したURLを設定します。

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
```

`.env.example` をコピーしてリネームすると簡単です。
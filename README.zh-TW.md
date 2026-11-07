# party-hud

[English](README.md)

把 coding agent 畫成 RPG 隊伍的 tmux 外掛，顯示在側欄。
每個 tmux session 是一個**小隊**，裡面跑的 agent（Claude Code、Codex、agy、Grok）是**隊員**：
有頭像、狀態、**HP**（剩餘 context）和 **SP**（prompt cache 還剩幾分鐘）。

<img src="docs/img/window.png" width="780" alt="一個 tmux window：左邊是 party-hud 側欄，有四個小隊和三張隊員卡；右邊的 pane 有 agent 在工作">

- **一眼看出誰在等你**：
  - 有人等你回應，小隊變橘色。
  - 有人做完但你還沒看，小隊變綠色。
  - 有人的快取過期了，小隊顯示紫色 `zzz 1`。
  - 有人閒置，小隊顯示灰色 `·1`。
  - 你沒在看的 window 會響鈴。
- **直接跳過去**：`n` 跳到下一個等你的隊員，沒有等你的就跳到做完的。`Enter` 切到那個隊員的 pane。
- **知道什麼時候該 compact**：
  - HP 是剩餘的 context（`620k/1M`），剩不到 10% 會閃爍。
  - SP 是快取倒數（`59/60m`）。歸零後，下一句話會重新讀入整段 context。
- **很省資源**：
  - 不管開幾個側欄，只有一個行程負責收集資料，最多每 2 秒一次。其他側欄只讀共用的快照檔。每個側欄每秒醒來一次，畫面有變才重畫。
  - 只有看得到的側欄會留著行程（每個約 25 MB）；看不到的會停掉，切到那個 window 時再重新啟動。
  - 只用 Python 標準函式庫，沒有常駐服務，不連網。數據見 [效能](docs/performance.md)。

另一個 window 的 Claude Code 停下來問你問題：它的小隊變成橘色，按 `n` 選到它，再按 `Enter` 跳過去。

<img src="docs/img/demo.gif" width="780" alt="螢幕錄影：畫面停在 Codex 時，另一個 window 的 Claude 隊員變成橘色、顯示 wait；在側欄按 n 再按 Enter，切到那個 window，Claude 正在問你喜歡哪個顏色">

## 怎麼看隊員卡

<img src="docs/img/card.png" width="590" alt="一張隊員卡，編號標出：agent 種類、頭像、職業圖示與名稱、狀態、HP、模型、SP、子代理">

| 編號 | 意思 |
|---|---|
| 1 | agent 種類：claude、codex、agy 或 grok |
| 2 | 頭像：8 種職業之一，依 session id 分配，同一小隊不重複 |
| 3 | 職業圖示和名稱：Claude Code 的 session 名稱（`/rename` 或自動標題），沒有才用 tmux window 名稱；其他 agent 顯示種類（`codex`、`agy`、`grok`） |
| 4 | 狀態：busy（工作中）、idle（閒置）、wait（等你）、done（做完） |
| 5 | HP：剩餘的 context |
| 6 | 模型 |
| 7 | SP：prompt cache 還剩幾分鐘 |
| 8 | 正在跑的子代理數量 |

上面的小隊清單也一樣：每個 tmux session 有一面隊徽，你正在看的小隊有金色底和左邊的金條，側欄自己所在的 session 有定位圖示。

## 需求

- 跑 tmux 的機器要是 Linux 或 macOS。
  - SSH 也能用：全部都在遠端跑，本機的終端機只負責畫面。
- tmux 3.3 以上，Python 3.10 以上。macOS 內建的 `python3` 是 3.9，請改用 Homebrew 的版本。
- 終端機要用 [Nerd Font](https://www.nerdfonts.com/)。
- 頭像和隊徽要用 [Ghostty](https://ghostty.org/) 或 [Kitty](https://sw.kovidgoyal.net/kitty/)，因為要支援 Kitty 圖片協定的 Unicode 佔位字元。其他終端機會自動改用文字版。

## 安裝

用 [TPM](https://github.com/tmux-plugins/tpm)（tmux 外掛管理器）：

```tmux
set -g @plugin 'mangow314/party-hud'
```

或者 clone 到任何地方，在 `~/.tmux.conf` 加一行 `run-shell ~/path/to/party-hud/party.tmux`。

### Claude Code 的 HP（建議設定）

Claude Code 每次更新 statusline 都會傳入一段 JSON。把這段 JSON 也轉給 party-hud，HP 就會顯示真正的 context 上限和模型名稱。加在你的 statusline 腳本裡，也就是 `~/.claude/settings.json` 的 `statusLine.command` 指向的那支：

```bash
input=$(cat)
printf '%s' "$input" | ~/.tmux/plugins/party-hud/integrations/claude-statusline.sh
# …你原本的 statusline，改用 "$input"…
```

沒有設定的話，HP 會從 transcript 推估。細節見 [docs/integrations.md](docs/integrations.md)。

### HP／SP 血條的終端機設定

血條是彩色底線。在 Ghostty 把底線往下移一點、加粗一點比較好看：

```
adjust-underline-position = 2
adjust-underline-thickness = 3
```

透過 SSH 連線的話，遠端要有你終端機的 terminfo（記錄終端機支援哪些功能的檔案）。Ghostty 可以設定 `shell-integration-features = ssh-terminfo` 自動處理。

## 按鍵

| 按鍵 | 動作 |
|---|---|
| `prefix C-t` | 在所有 window 開／關側欄 |
| `prefix P` | popup 版 |
| `prefix a` | 不開任何東西，直接跳到下一個等你或做完的隊員 |
| `prefix R` | 任務回報：看等你或做完的隊員最後交出的報告 |
| `j`／`k` | 同一隊的下一位／上一位（到頭尾就停） |
| `J`／`K` | 下一隊／上一隊 |
| `1`–`9` | 這隊第 N 位 |
| `Enter` | 切到那位隊員的 pane |
| `n` | 下一個等你的，沒有的話下一個做完的 |
| `v` | 看那位隊員最後幾行輸出 |
| `r` | 在側欄裡：用 pane 開選中隊員的任務回報 |
| `Esc`／`q` | 回到原本的 pane／收起全部側欄 |

拖側欄邊框可以調寬度，所有側欄會一起記住新寬度，最窄 30 欄。

### 任務回報

隊員做完或停下來等你時，`prefix R` 會開一個 pane，顯示它最後交出的報告：標題寫 `Quest complete`，旁邊是隊員頭像（Ghostty、Kitty），下面是隊員名稱、花了多久（從你送出指令到它回完）、剩下的 HP，再下面是報告本文，Markdown 會上色。tmux 3.8 以上是浮在視窗上的 pane；更舊的 tmux 則把目前視窗切成兩半。

- Claude Code 的報告是最後一輪回覆裡、最後一次工具呼叫之後的文字；Codex 是最後一次完成的回覆。
- 沒有報告時改顯示 pane 最後幾行（`Last output`）：agy、Grok 一律如此；在等你核准或回答問題的 Claude 通常也是，問題就在那幾行裡。
- 整份報告一次印出，要捲動或複製請用 tmux 的 copy-mode（`prefix [`）。
- 在浮動的報告 pane 上再切分出 pane，關掉那個 pane 後報告 pane 不會長回原大小；按 `q` 再按 `prefix R` 重開即可。
- `n` 看下一份，`Enter` 切到那位隊員的 pane，`q`／`Esc` 關閉這個 pane。
- 看完報告不會清掉「做完」的標記，切到那個 pane 才會。

想在狀態列看到有幾份報告，collector 會把「等你或做完的隊員數」寫進 tmux 變數 `@party_reports`：

```tmux
set -ag status-right '#{?#{@party_reports}, 報告 #{@party_reports},}'
```

## 選項

設定在 `~/.tmux.conf`，要放在載入外掛之前。

| 選項 | 預設 | 意思 |
|---|---|---|
| `@party_key_toggle` | `C-t` | 開／關側欄的鍵 |
| `@party_key_popup` | `P` | popup 的鍵 |
| `@party_key_next` | `a` | 「跳到下一個等你的」的鍵 |
| `@party_key_report` | `R` | 任務回報的鍵 |
| `@party_art` | `auto` | `on`／`off` 強制開／關圖片；`auto` 在 Ghostty、Kitty 自動開 |
| `@party_sidebar_width` | `34` | 側欄寬度（欄） |

圖片靠 tmux 的 `allow-passthrough` 送到終端機。party-hud 只對自己的側欄 pane 開這個選項，其他 pane 裡的程式仍然不能把控制序列直接送到你的終端機。`prefix P` 的 popup 不是 pane，要在 `~/.tmux.conf` 自己全域設 `allow-passthrough on` 才會有圖片（這樣每個 pane 都能繞過 tmux）；沒設就用文字版。

## 怎麼認出隊員

| Agent | 狀態 | HP | SP |
|---|---|---|---|
| Claude Code | `~/.claude/sessions/*.json`（busy／idle） | statusline 整合，或從 transcript 推估 | 從 transcript 讀快取 TTL |
| Codex | 畫面有沒有變化 | `~/.codex/sessions` 的 rollout 紀錄檔 | 拿不到（`--`） |
| agy、Grok | 畫面有沒有變化 | `--` | `--` |

pane 的指令是上面這些 agent，或它的子行程裡有這些 agent（例如跑在 `node` 或包裝腳本底下），就算隊員。
Claude Code 自己回報在等你時，隊員會顯示等你，不用另外設定。
有用 [workmux](https://github.com/raine/workmux) 的話，也會讀它的「等你／完成」狀態。
所有資料都只在本機讀取，不會送出去。更多細節見 [docs/architecture.md](docs/architecture.md)。

## 限制

- 每個使用者只支援一個 tmux server。所有 server 共用同一個狀態資料夾，而 pane 編號（`%5`）在不同 server 之間會重複，
  所以另開第二個 server（`tmux -L 名稱`）時，側欄可能顯示錯的隊員或跳錯 pane。同一個 server 裡開多個 session 沒有問題。

## 致謝與授權

- 程式碼：[MIT](LICENSE)。
- 圖片：[CC0](art/LICENSE)，在本機用 FLUX.2 [klein] 4B（Apache-2.0）生成。提示詞、seed 和完整流程寫在 [ASSETS.md](ASSETS.md)。

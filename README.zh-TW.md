# party-hud

[English](README.md)

把 coding agent 畫成 RPG 隊伍的 tmux 外掛，顯示在側欄。
每個 tmux session 是一個**小隊**，裡面跑的 agent（Claude Code、Codex、agy、Grok）是**隊員**：
有頭像、狀態、**HP**（剩餘 context）和 **SP**（prompt cache 還剩幾分鐘）。

<img src="docs/img/window.svg" width="780" alt="一個 tmux window：左邊是 party-hud 側欄，有四個小隊和三張隊員卡；右邊的 pane 有 agent 在工作">

- **一眼看出誰在等你**：
  - 有人等你回應，小隊變橘色。
  - 有人做完但你還沒看，小隊變綠色。
  - 有人的快取過期了，小隊顯示紫色 `zzz 1`。
  - 有人閒置，小隊顯示灰色 `·1`。
  - 你沒在看的 window 會響鈴。
- **直接跳過去**：`n` 跳到下一個等你的隊員，沒有等你的就跳到做完的。`Enter` 切到那個隊員的 pane。
- **知道什麼時候該 compact**：
  - HP 是剩餘的 context（`620k/1M`），剩不到 10% 會閃爍。
  - SP 是快取倒數（`59/60m`）。歸零後，下一句話會重新讀入整段 context。沒有快取資料的隊員不顯示 SP 列。
  - 側欄很窄時先截斷名字，HP 數值（剩餘/上限）保持完整。連續的空小隊收成一列 `+N empty`（游標所在的小隊一律顯示）。小隊太多時 Squads 框會縮小並以目前檢視的小隊為中心，上下以 `▲ n more` / `▼ n more` 表示被藏起來的數量，選取的卡片永遠看得到。
- **看得到變化**：隊員變成做完或等你時，卡片框線慢速閃約 4 秒，Squads 列表中該 Squad 的名稱也會跟著閃，在別的 Squad 也看得到；HP 或 SP 大幅變化（5 以上）時，數字旁會顯示變化量約 10 秒：HP 以百分點表示（`+40%`），SP 以分鐘表示（`-12`）。`set -g @party_anim off` 可關閉。
- **很省資源**：
  - 不管開幾個側欄，只有一個行程負責收集資料，最多每 2 秒一次。其他側欄只讀共用的快照檔。每個側欄每秒醒來一次，畫面有變才重畫。
  - 只有看得到的側欄會留著行程（每個約 25 MB）；看不到的會停掉，切到那個 window 時再重新啟動。
  - 只用 Python 標準函式庫，沒有常駐服務，不連網。數據見 [效能](docs/performance.md)。

另一個 window 的 Claude Code 停下來問你問題：它的小隊變成橘色，按 `n` 選到它，再按 `Enter` 跳過去。

<img src="docs/img/demo.gif" width="780" alt="螢幕錄影：畫面停在 Codex 時，另一個 window 的 Claude 隊員變成橘色、顯示 wait；在側欄按 n 再按 Enter，切到那個 window，Claude 正在問你喜歡哪個顏色">

## 怎麼看隊員卡

<img src="docs/img/card.svg" width="590" alt="一張隊員卡，編號標出：agent 種類、頭像、職業圖示與名稱、狀態、HP、模型、SP、子代理">

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
| `prefix R` | 任務回報：先看等你或做完的，沒有的話看目前視窗的隊員；`n` 輪到所有隊員 |
| `j`／`k` | 同一隊的下一位／上一位（到頭尾就停） |
| `J`／`K` | 下一隊／上一隊 |
| `1`–`9` | 這隊第 N 位 |
| `Enter` | 切到那位隊員的 pane |
| `n` | 下一個等你的，沒有的話下一個做完的 |
| `v` | 看那位隊員最後幾行輸出 |
| `r` | 在側欄裡：用 pane 開選中隊員的任務回報 |
| `Esc`／`q` | 回到原本的 pane／收起全部側欄 |
| `?` | 開／關按鍵說明（任務回報裡也能用）；說明開著時 `Esc`／`q` 只關說明 |

<img src="docs/img/help.svg" width="780" alt="任務回報頁的按鍵說明：置中的框裡列出每個按鍵和用途，後面的報告頁變暗">

拖側欄邊框可以調寬度，所有側欄會一起記住新寬度，最窄 30 欄。

### 任務回報

<img src="docs/img/report.svg" width="780" alt="寬 pane 裡已完成隊員的任務回報頁：上方 Quest Complete 橫幅，左邊粗線框有頭像、名稱、TOOK、WAITED、ASKED、FILES、WHERE；右邊是 Markdown 報告，有標題、條列、小表格和程式碼區塊">

`prefix R` 會開一個 pane，先顯示做完或等你的隊員最後交出的報告；沒有的話顯示目前視窗的隊員（閒置的看最後一份報告，工作中的看進行中頁），按 `n` 輪到所有隊員。Ghostty、Kitty 上，頁面最上方是一張像素橫幅（最高 10 列，窄版最寬 80 欄，標題畫在圖裡），橫幅下面是隊員頭像；其他終端機則是一行文字標題。接著是隊員名稱、花了多久（從你送出指令到它回完）、剩下的 HP，再下面是報告本文，Markdown 會上色（表格放得下就排成對齊的欄位，放不下就改成逐列「欄名：內容」）。tmux 3.8 以上是浮在視窗上的 pane；更舊的 tmux 則把目前視窗切成兩半。

- pane 寬 100 欄以上（且有圖）時，頁面分成左右兩欄：左邊粗線框裡是金框大頭像（約與橫幅同高、置中、頂端與橫幅對齊）、名稱、狀態標籤（`✓ Complete` 或 `! Waiting`）、`kind · squad`、`TOOK` 和 `WAITED`（標籤靠左、值靠右；等你時 `WAITED` 那列有橙色底帶和 `!`）、`ASKED`（這輪你親手輸入的提問，最多 3 列；貼上的內容只在你沒另外打字時顯示；slash 指令顯示 `/name args`，通知等系統訊息不算）、`FILES`（每個檔前有 `•`；這輪改過的檔，相對 pane 目錄，太長從左截斷，最多 6 列、超過寫 `+N more`；其後一列 `14 cmds · 3 agents`，為 0 的項目省略；subagent 改的檔不計入）、`WHERE`（完整路徑（家目錄寫成 `~`）與 git 分支），框一路延伸到 pane 左下角，按鍵提示在框內最後一列。小標題是像素圖標籤（寶石、光暈、各自分色：`TOOK` 青、`WAITED` 橙、`ASKED` 金、`FILES` 與 `WORK` 綠、`WHERE` 紫；沒有圖時改用同色粗體文字），框線顏色依狀態：完成金、等你橙、有報告藍、進行中藍紫。右邊是橫幅（最高 10 列，寬度撐滿右欄；pane 極寬時最扁到 8:1，右邊留空）和報告本文；本文與橫幅同寬換行，程式碼區塊和 `Last output` 不受限。
- 每換一頁（開啟後第一頁、`n`／`N`）有約 0.4 秒的開場動畫：橫幅和左欄直接出現，報告本文分幾步露出。任何鍵盤或滑鼠輸入都會立刻跳過動畫，並照常處理。`set -g @party_anim off` 可關閉。
- Claude Code 的報告是最後一輪回覆裡、最後一次工具呼叫之後的文字；Codex 是最後一次完成的回覆。
- 沒有報告時改顯示 pane 最後幾行（`Last output`）：agy、Grok 一律如此；在等你核准或回答問題的 Claude 通常也是，問題就在那幾行裡，顏色保留 pane 原本的樣子。等你的隊員一律用 `Waiting` 橫幅（有報告或還有 subagent 在跑也一樣）；其他沒有報告的用 `Last output`。
- 橫幅依隊員狀態而定：`Quest Complete`（做完、沒有東西還在跑）、`Waiting for You`（等你回答）、`Report`（閒置隊員的完整報告，或任何還有 subagent 在跑的隊員的報告）、`Last Output`（還沒有完整報告）。

  <img src="docs/img/banners.svg" width="480" alt="四種報告橫幅由上到下排列，每張下方一行說明何時出現：Quest Complete、Waiting for You、Report、Last Output">

- 還在工作的 Claude Code 或 Codex 隊員顯示「進行中」頁（畫面上的字是英文）：一列狀態（`Working · 12m 03s`，從你最後輸入的提問算起）、`Now` 區塊（最新一次工具呼叫與最新文字的最後幾列），再接上一輪的報告。頁面開著時約每 1.5 秒重讀一次，隊員做完或等你時自動換成正式報告。左欄顯示這輪的 `ASKED`、`FILES`、`WHERE`，以 `RUNNING` 標籤（值是已跑多久）取代 `TOOK`。

  <img src="docs/img/report-working.svg" width="780" alt="工作中隊員的進行中頁：一列狀態與已跑時間、`Now` 區塊（最新工具呼叫與文字）、`Previous report` 與上一輪的報告；左欄有 RUNNING 標籤">

- 分欄頁面的左欄固定不動，只有右欄（橫幅和本文）捲動；窄 pane 則整頁一起捲。用 `j`／`k`、方向鍵或滾輪捲一列，`PgUp`／`PgDn` 捲一頁，`g`／`G` 跳到頂／底。放得下的報告不會動。要複製文字請按住 `Shift` 拖曳（交給終端機選取）。
- 縮放 pane 時報告立刻以新尺寸就地重畫（算得出來就畫，不另外延遲），不清整個畫面；圖片等縮放停下片刻後才跟上。
- 在浮動的報告 pane 上再切分出 pane，關掉那個 pane 後報告 pane 不會長回原大小；按 `q` 再按 `prefix R` 重開即可。
- `n` 看下一份，`N` 看上一份，`Enter` 切到那位隊員的 pane，`q`／`Esc` 關閉這個 pane，`?` 列出所有按鍵（再按 `?`／`Esc`／`q` 回到原本位置）。
- 看完報告不會清掉「做完」的標記，切到那個 pane 才會。
- Claude Code 隊員還有 subagent 在跑時，同樣有報告頁。標題從 `Quest complete` 改成 `N subagents still running`（N 是進行中的
  subagent 數，只有一個時是 `1 subagent still running`），報告下方逐一列出進行中的 subagent，附名稱與 `running`。
- 這一輪（你最後一次送出之後）完成的 subagent 也列在報告下方，附上它最後交回的報告（Markdown 會上色）。

想在狀態列看到有幾份報告，collector 會把「等你或做完的隊員數」寫進 tmux 變數 `@party_reports`：

```tmux
set -ag status-right '#{?#{@party_reports}, 報告 #{@party_reports},}'
```

### 從指令讀報告

```sh
python3 ~/.tmux/plugins/party-hud/party.py --report-text PANE [--wait] [--timeout SEC]
```

`PANE` 是 tmux pane id，例如 `%12`。不加 `--wait`，立刻印出該隊員目前的報告。加 `--wait`，隊員還在工作、還有 subagent
在跑、或有已完成的 subagent 主對話尚未回應時，會等這些狀況結束再印。`--timeout` 是最多等幾秒（預設 600）。

| 退出碼 | 意思 |
|---|---|
| 0 | 已印出報告。已知 agent 但沒有報告時也是 0：stdout 為空，stderr 寫 `no report for PANE` |
| 2 | 參數錯誤（不是 pane id、逾時值不合法）或 pane 不存在 |
| 3 | 等待時 `--timeout` 用完 |
| 4 | pane 存在，但不是已知 agent |

### 協作指令

`--summon AGENT` 開一個跑 `claude`、`codex`、`agy` 或 `grok` 的 pane，等它可以輸入後印出 pane id。`--ask PANE TEXT`
把文字貼進 agent 的 pane、按 Enter，並印出送出的時間。搭配上面的 `--report-text PANE --wait --after EPOCH`，一個 agent 就能把工作交給另一個並等回覆：

```sh
m=$(python3 ~/.tmux/plugins/party-hud/party.py --summon agy)
t=$(python3 ~/.tmux/plugins/party-hud/party.py --ask "$m" "你的問題")
python3 ~/.tmux/plugins/party-hud/party.py --report-text "$m" --wait --after "$t"
```

`--summon` 退出碼：0 就緒、2 參數錯誤或 tmux 失敗、3 逾時（可加 `--cwd DIR`、`--window`、`--timeout SEC`）。`--summon codex --read-only` 以 codex 的強制唯讀沙箱（`-s read-only`）啟動；其他 agent 沒有這種模式，會以 2 退出。`--ask`：0 已送出、2 pane 錯誤或不存在、4 不是 agent。
側欄仍然只讀；這些指令只在被呼叫時才開 pane 或送按鍵。

每一輪問答都會存到 `~/.local/state/party-hud/crew/`（有設 `XDG_STATE_HOME` 時改用 `$XDG_STATE_HOME/party-hud/crew/`）下的 `<開始時間 UTC>-<pane id>/round-NNN/`
（`question.md`、`reply.md`、`meta.json`），事後可查。`--summon` 會刪掉 14 天沒動的 session 目錄。存檔失敗時，`--ask`、
`--report-text`、`--summon` 做完事後以 5 退出，原因印在 stderr。

### Claude Code skill（party-crew）

`skills/party-crew/SKILL.md` 是一份很短的 Claude Code skill，教 Claude 何時、怎麼用 `--summon`、`--ask`、`--report-text`。裝好後，跟 Claude 說「找 codex 給這個 diff 第二意見」，它會自己開 pane、送出問題、讀回答案。任務相符時 Claude 會自動載入，也可以打 `/party-crew` 叫它。

連結一次即可（TPM 的安裝路徑；用 clone 的話換成你的 checkout 路徑）：

```sh
mkdir -p ~/.claude/skills
ln -s ~/.tmux/plugins/party-hud/skills/party-crew ~/.claude/skills/party-crew
```

Claude Code 的 Bash 沙箱開著時，這些指令連不到 tmux socket（`Error connecting to /tmp/tmux-1000/default (Operation not permitted)`）。要讓它們能跑，在 `~/.claude/settings.json` 的 `sandbox.excludedCommands` 加上 party.py：

```json
"excludedCommands": ["python3 ~/.tmux/plugins/party-hud/party.py *"]
```

- 符合的指令在沙箱外執行，沒有檔案與網路限制，只加這一條。
- 比對的是指令文字：整行要每一段都符合，含 `$(...)`、重導向或 `cd` 的整行仍留在沙箱內。所以 Claude 要把每一步分開呼叫，從輸出讀 pane id 與時間，不能寫成上面那種 `m=$(...)` 的寫法。
- `sandbox.network.allowAllUnixSockets` 也能解，但會放行所有 Unix socket，不建議。

## 選項

設定在 `~/.tmux.conf`，要放在載入外掛之前。

| 選項 | 預設 | 意思 |
|---|---|---|
| `@party_key_toggle` | `C-t` | 開／關側欄的鍵 |
| `@party_key_popup` | `P` | popup 的鍵 |
| `@party_key_next` | `a` | 「跳到下一個等你的」的鍵 |
| `@party_key_report` | `R` | 任務回報的鍵 |
| `@party_art` | `auto` | `on`／`off` 強制開／關圖片；`auto` 在 Ghostty、Kitty 自動開 |
| `@party_anim` | `on` | 設為 `off` 關閉報告頁的開場動畫，以及側欄的卡片閃爍和 HP／SP 的 `+N`／`-N` 標籤 |
| `@party_sidebar_width` | `34` | 側欄寬度（欄） |

圖片靠 tmux 的 `allow-passthrough` 送到終端機。party-hud 只對自己的側欄 pane 開這個選項，其他 pane 裡的程式仍然不能把控制序列直接送到你的終端機。`prefix P` 的 popup 不是 pane，要在 `~/.tmux.conf` 自己全域設 `allow-passthrough on` 才會有圖片（這樣每個 pane 都能繞過 tmux）；沒設就用文字版。

## 怎麼認出隊員

| Agent | 狀態 | HP | SP |
|---|---|---|---|
| Claude Code | `~/.claude/sessions/*.json`（busy／idle） | statusline 整合，或從 transcript 推估 | 從 transcript 讀快取 TTL |
| Codex | 畫面有沒有變化 | `~/.codex/sessions` 的 rollout 紀錄檔 | 不顯示 |
| agy、Grok | 畫面有沒有變化 | `--` | 不顯示 |

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

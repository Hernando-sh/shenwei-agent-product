# ADR-005 · 确认是管线里的一步：变更集 + 绑定摘要与有效期的令牌；W2 用终端同步确认

日期 2026-11-07 · 状态 accepted · 关联 2.5 · 回答周 spec w02-quote §8「业务结果记在哪」

## 场景

写动作必须先问人（US-02、AC-03）。W5 才有 Java 确认服务与网页；W2 只有终端。要在不改 Loop、不给 W5 留返工的前提下，把"问人"做进管线。

## 选择

1. 确认是 ToolRuntime 管线的一步，不是工具内部的 `input()`：策略给出 confirm → 运行时把校验后的参数做成变更集（Changeset：operation_id、tool、kind、args、digest、summary）→ 交给 ConfirmationAdapter → 拿回 ConfirmToken → 校验 → 才执行。工具本身不知道有没有人确认过。
2. 令牌校验三件事缺一不可：同一 operation_id、同一 digest（tool + 参数的摘要，和 run / call 无关）、在有效期内（真实时钟，10 分钟）。改任何参数 → digest 变 → 原确认失效（W2-AC-07）。
3. 操作者的三种决定：同意（执行一次）、拒绝（不执行，业务结果 cancelled，回注模型"已取消，不要再请求"）、改参数（原变更集作废，把修改要求回注模型，由模型重新算价、重新请求保存，再确认一次）。没有拿到决定（EOF / 非交互）不等于同意。
4. 没有确认适配器的运行时，对 confirm 一律拒绝（confirmation_required）：不存在"没接确认通道就直接写"的配置。
5. 业务结果写独立事件 `run.outcome`（resolved / declined / cancelled），由运行时在能判定时写：写工具执行成功 → resolved；工具结果里 `outcome: declined`（约定字段，不认工具名）→ declined；确认被拒 → cancelled。没有该事件且 run 非 completed → failed。Loop 不改，所以不放进 run.completed。
6. 模式（ask / auto）是运行时的状态，`set_mode` 写 `mode.changed`；策略表决定两种模式下各档位的动作，报价台账写入（对外写）在 auto 下仍确认。

## 不做

不做挂起等人（W6：确认是同步阻塞的，终端里读一行）；不做确认的持久化与跨进程核验（W5 Java 确认服务）；不做改参数的自动重算（交回模型，参数变化要再走一次规则与算价）。

## 证据

T26–T29：未确认不写、同意后恰写一次；拿 2 台的令牌写 10 台 → digest_mismatch 不写；改参数 → 第二个变更集、写的是 10 台；拒绝 → cancelled；601 秒后的令牌 → expired；auto 下内部写不问、create_quote 仍问；mode.changed 事件。

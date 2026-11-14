# F07：撤销五张业务表的全局登录用户读取

2026-11-14 准备的代码修复，**尚未在生产执行**。本候选实施后将取代 D-101/S-13 中保留 `ssll_authenticated_read` 的方案；旧文档的生产观察不是本次部署验证。

`schemas/security_revoke_authenticated_ssll_read.sql` 是既有库的独立增量：对 `public.projects/pipeline_runs/stage_logs/outputs/reference_samples` 保持 RLS 开启，并删除名为 `ssll_authenticated_read` 的旧全局 SELECT 策略。其它策略、表级授权、service_role、public 看板视图均不改。fresh-install 的 `security_rls_public_ssll_tables.sql` 同样不再创建该策略。

## 部署前核实

1. 负责人提供当前五表的 RLS、全部 policy、表级 grants，以及 service_role 的角色属性快照。策略和表级 SELECT 授权是两道独立检查；不能只看其中一道。
2. 核实三生六部及其它消费者实际使用的身份。service_role 既要有表级权限，又应有 BYPASSRLS；不能只凭变量名判断。若发现 authenticated 的合法消费者，先列出它应访问的项目/工作区及所需策略，避免在部署后才发现依赖。
3. 核实没有其它 `USING(true)` 或等价的宽松读策略重新放行。这份最小增量只删除已定位的旧策略名，不冒充覆盖未知的生产策略。
4. 在一次性非生产数据库运行 `scripts/check_ssll_authenticated_read.sql`。该测试会建立合成 public 表和角色，**只用于空的本地/CI数据库**；不要在生产运行。

## 部署与验收

确认调用者后，由负责人按正常迁移流程执行增量 SQL。文件是事务性的且可重跑；缺少五表之一会报错，不静默跳过。执行后核对：旧策略数为 0、RLS 仍开启，真实 service_role 消费者继续读取；authenticated 只能读其它合法窄策略允许的记录（没有其它策略时为 0 行）；anon 看板视图与聚合数据照常。

本次不更改 Auth 注册开关、不轮换密钥、不连接生产。已有快照中的旧权限不证明当前已撤回；以部署后的实际角色验收为准。回退应根据已核实的消费者建立所需的窄策略，不默认恢复跨客户全局读取。

-- 4a 先看(只读): 每列有几格会被回滚、几格不动。不动的两种:
--    changed_since_keep  = 恢复之后被同步 / essence / 人改成了别的值;
--    essence_rewrote_keep = 恢复之后 essence 又写过这一篇(重标落在同一个标签上, 值碰巧和恢复的一样)。
--      audit_row_change 只记真变了的列, 同标签重标那条 UPDATE 里没有 content_format, 光看库值分不出来;
--      这种格子回滚成 NULL 之后 essence_annotated_at 非空、essence 不会再补, 又是事故那种卡死状态。
--    判「之后 essence 写过」: 恢复之后有一条 UPDATE 把 essence_annotated_at 改成了非空。修复自己那几条
--    UPDATE 不碰 essence_annotated_at, 所以不会被算进来(planned_at 是恢复事务的 now(), 换成 UTC 再和不带
--    时区的 occurred_at 比, 跟跑这条查询的会话时区无关)。
WITH p AS (
  SELECT p.col, p.restore_v,
         CASE p.col
           WHEN 'content_format'  THEN to_jsonb(t.content_format)
           WHEN 'target_audience' THEN to_jsonb(t.target_audience)
           WHEN 'user_pain_point' THEN to_jsonb(t.user_pain_point)
           ELSE                        to_jsonb(t.product_focus) END AS cur,
         EXISTS (
           SELECT 1 FROM truth_vault.audit_log a
           WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes'
             AND a.row_id = p.note_id AND a.operation = 'UPDATE'
             AND a.occurred_at > (p.planned_at AT TIME ZONE 'UTC')
             AND a.changed_cols -> 'essence_annotated_at' -> 1 <> 'null'::jsonb) AS essence_rewrote
  FROM truth_vault.repair_notes_essence_cols_20261020 p
  JOIN truth_vault.notes t USING (note_id)
)
SELECT col,
       count(*) FILTER (WHERE restore_v = cur AND NOT essence_rewrote) AS will_roll_back,
       count(*) FILTER (WHERE restore_v = cur AND essence_rewrote)     AS essence_rewrote_keep,
       count(*) FILTER (WHERE restore_v IS DISTINCT FROM cur)          AS changed_since_keep
FROM p
GROUP BY 1;

-- 4b 回滚: 只回滚「库值还等于修复写进去的那个、且恢复之后 essence 没再写过这一篇」的格子, 改回备份里的值(都是 NULL)
--    别在 daily-sync / backfill-essence 正在跑的时候跑。LOCK 先等正在写 notes 的事务提交、再挡住新的写入直到 COMMIT
--    (几秒): 不锁的话, 名单建好之后、UPDATE 之前 essence 又写了这一篇, 照样会被回滚成 NULL、卡死(codex review on TV#211)。
BEGIN;
LOCK TABLE truth_vault.notes IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE rollback_skip_essence ON COMMIT DROP AS
SELECT DISTINCT p.note_id
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.audit_log a
  ON a.schema_name = 'truth_vault' AND a.table_name = 'notes'
 AND a.row_id = p.note_id AND a.operation = 'UPDATE'
 AND a.occurred_at > (p.planned_at AT TIME ZONE 'UTC')
 AND a.changed_cols -> 'essence_annotated_at' -> 1 <> 'null'::jsonb;
UPDATE truth_vault.notes t SET content_format = b.content_format
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.backup_notes_essence_cols_20261020 b USING (note_id)
WHERE p.note_id = t.note_id AND p.col = 'content_format'
  AND to_jsonb(t.content_format) = p.restore_v
  AND p.note_id NOT IN (SELECT note_id FROM rollback_skip_essence);
UPDATE truth_vault.notes t SET target_audience = b.target_audience
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.backup_notes_essence_cols_20261020 b USING (note_id)
WHERE p.note_id = t.note_id AND p.col = 'target_audience'
  AND to_jsonb(t.target_audience) = p.restore_v
  AND p.note_id NOT IN (SELECT note_id FROM rollback_skip_essence);
UPDATE truth_vault.notes t SET user_pain_point = b.user_pain_point
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.backup_notes_essence_cols_20261020 b USING (note_id)
WHERE p.note_id = t.note_id AND p.col = 'user_pain_point'
  AND to_jsonb(t.user_pain_point) = p.restore_v
  AND p.note_id NOT IN (SELECT note_id FROM rollback_skip_essence);
UPDATE truth_vault.notes t SET product_focus = b.product_focus
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.backup_notes_essence_cols_20261020 b USING (note_id)
WHERE p.note_id = t.note_id AND p.col = 'product_focus'
  AND to_jsonb(t.product_focus) = p.restore_v
  AND p.note_id NOT IN (SELECT note_id FROM rollback_skip_essence);
COMMIT;

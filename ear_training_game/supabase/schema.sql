-- 在 Supabase Dashboard → SQL Editor 中执行本脚本
-- 学生答题记录表

create table if not exists public.answer_records (
    id            uuid primary key default gen_random_uuid(),
    user_id       text not null,
    question_type text not null,
    is_correct    boolean not null,
    wrong_at      timestamptz,
    answered_at   timestamptz not null default now(),
    created_at    timestamptz not null default now(),

    -- 答错时必须有错题时间；答对时 wrong_at 必须为 NULL
    constraint answer_records_wrong_at_check check (
        (is_correct = true  and wrong_at is null)
        or
        (is_correct = false and wrong_at is not null)
    )
);

comment on table public.answer_records is '乐理听音小游戏答题记录';
comment on column public.answer_records.user_id is '学生标识（昵称或 Supabase Auth UUID）';
comment on column public.answer_records.question_type is '题目类型，如 interval_p4_p5';
comment on column public.answer_records.is_correct is '是否答对';
comment on column public.answer_records.wrong_at is '答错时刻（仅错题有值）';
comment on column public.answer_records.answered_at is '作答时刻';

create index if not exists answer_records_user_id_idx
    on public.answer_records (user_id);

create index if not exists answer_records_question_type_idx
    on public.answer_records (question_type);

create index if not exists answer_records_wrong_at_idx
    on public.answer_records (wrong_at)
    where wrong_at is not null;

-- 行级安全（RLS）
alter table public.answer_records enable row level security;

-- 演示环境：允许匿名插入与按 user_id 查询（生产环境请收紧策略）
drop policy if exists "allow_insert_answer_records" on public.answer_records;
create policy "allow_insert_answer_records"
    on public.answer_records
    for insert
    to anon, authenticated
    with check (true);

drop policy if exists "allow_select_own_answer_records" on public.answer_records;
create policy "allow_select_own_answer_records"
    on public.answer_records
    for select
    to anon, authenticated
    using (true);

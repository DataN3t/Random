Nice, this is a meaty one 😄 Let’s untangle it step by step.

1. What “Must declare the scalar variable @schema” really means

That error means:

The engine is trying to run part of your script without seeing the DECLARE @schema first.

In other words, in the Synapse Copy activity “Source query” context, your script is not being treated as one monolithic batch the way SSMS does. The service is effectively trying to execute a fragment like:

... WHERE c.object_id = OBJECT_ID(QUOTENAME(@schema) + N'.' + QUOTENAME(@table))


before it has processed:

DECLARE @schema sysname = N'tdfschema';
DECLARE @table  sysname = N'Key.Wrd4';


So:

In SSMS, that big dynamic script with DECLARE, CTEs, SET @sql = ..., EXEC sys.sp_executesql @sql does work.

In the Copy activity’s Source query, the same text is not supported reliably. That field is designed for a single final SELECT, not a procedural batch with variables and EXEC.

That’s why you now see both:

Earlier: REPLACE-related syntax errors.

Now: Must declare the scalar variable "@schema".

They’re both symptoms of “this environment doesn’t like your complex batch”.

2. Why your “working” script produced weird data

Your original dynamic script is doing a bunch of type conversions:

WHEN typ_name IN ('image','varbinary','binary','rowversion','timestamp')
    THEN N'CAST(' + QUOTENAME(col_name) + N' AS varbinary(max)) AS ' + QUOTENAME(safe_name)
WHEN typ_name IN ('datetimeoffset')
    THEN N'CAST(' + QUOTENAME(col_name) + N' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
...


That’s why in the Parquet:

Exists_1                         Max*_StatementDate__2   ...
0 b'\x01\x00\x00\x00'           2025-10-23 10:15:00.000000000 ...
1 b'\xab\xcd\x00\x00'           2025-10-23 08:00:00.000000000 ...
...


you see:

b'\x01\x00\x00\x00' etc. — that’s just your viewer showing varbinary bytes.

The 0001-01-01T... becoming something else — because of the specific cast / min date bounds interaction.

So:

✅ The script was doing what it was told (casting stuff).

❌ That’s not what you want for a “format-preserving” mask pipeline where you later send it back to the customer’s SQL server.

You mostly want:

Same data types as the original table.

Clean column names that are safe in downstream systems.

3. Hard truth: the Copy activity query is not the place for clever dynamic SQL

Given the behavior you’re seeing:

You cannot rely on DECLARE @schema, CTEs that build metadata, SET @sql, EXEC sp_executesql inside the Source query.

Even if it sometimes “kinda works”, it’s brittle and will keep throwing these weird errors.

For the Copy activity, think:

“One final SELECT that returns rows. No fancy scripting.”

So the safe pattern is:

Either SELECT * FROM [schema].[table] and handle renames in mapping.

Or a static SELECT that:

References your ugly column names with brackets.

Gives them nice, sanitized aliases.

Does no type casting, unless you really need it.

4. Concrete fix for this table (tdfschema.Key.Wrd4)

From your sample, this table has columns like:

Exists

Max*(StatementDate)

From

0; <= 100

Identity

''

# empty fields

Let’s write a simple, static query that:

Keeps each column’s data type.

Gives you clean, escape-safe names (letters / digits / underscores only).

Paste this into the Source query box:

SELECT
    [Exists]               AS [Exists],
    [Max*(StatementDate)]  AS [Max_StatementDate],
    [From]                 AS [From_],
    [0; <= 100]            AS [Range_0_100],
    [Identity]             AS [Identity_],
    ['']                   AS [EmptyString],
    [# empty fields]       AS [EmptyFields]
FROM [tdfschema].[Key.Wrd4] WITH (NOLOCK);


What this does:

Data:

No CAST, CONVERT, or sql_variant magic → all types come out as they are in the source table.

The Parquet sink will infer types from SQL natively.

Column names in Parquet:

Exists

Max_StatementDate

From_

Range_0_100

Identity_

EmptyString

EmptyFields

All of these are:

No spaces,

No quotes, percent signs, slashes, etc.

Friendly for FPE + round-tripping back into SQL.

Try this for Key.Wrd4 and check the resulting Parquet: you should see both sane column names and sane values.

5. How to generalize this beyond a single table

You’ve basically got three realistic options, ordered from least magic to most:

Option A – SELECT * + mapping (no SQL gymnastics)

Source query:

SELECT * FROM [tdfschema].[Key.Wrd4] WITH (NOLOCK);


In the Copy activity → Mapping tab:

Map ugly source column names (Max*(StatementDate), 0; <= 100, etc.)

To sanitized sink names (Max_StatementDate, Range_0_100, etc.).

Pros:

Works for any table with no SQL changes.

All data types preserved automatically.

Cons:

You have to configure mappings once per table.

Option B – Static SELECT per table (like I showed)

For a handful of tricky tables, write a tailored query:

SELECT
    [Ugly Name 1] AS [NiceName1],
    [Ugly Name 2] AS [NiceName2],
    ...
FROM [schema].[SomeTable] WITH (NOLOCK);


Pros:

Full control over which columns you export / how they are named.

Types preserved.

Keeps mapping simple (1:1).

Cons:

A bit of manual work per table.

Option C – Upstream view (if you ever get DB perms)

If you ever do get someone on the SQL side to help:

CREATE VIEW [tdfschema].[vw_KeyWrd4_Safe] AS
SELECT
    [Exists]               AS [Exists],
    [Max*(StatementDate)]  AS [Max_StatementDate],
    [From]                 AS [From_],
    [0; <= 100]            AS [Range_0_100],
    [Identity]             AS [Identity_],
    ['']                   AS [EmptyString],
    [# empty fields]       AS [EmptyFields]
FROM [tdfschema].[Key.Wrd4];


Then in Synapse:

SELECT * FROM [tdfschema].[vw_KeyWrd4_Safe] WITH (NOLOCK);


Pros:

Reusable across all pipelines.

No need for dynamic SQL anywhere.

Cons:

Requires DB-side change (which you said you currently can’t do).

6. TL;DR for you right now

The @schema error = Copy activity can’t handle your multi-statement batch with variables + dynamic SQL.

The weird data from the earlier script = you were casting types in ways you don’t actually want.

For this pipeline, the most robust fix is:

Ditch dynamic SQL / DECLARE / EXEC.

Use a single static SELECT that:

Brackets the original weird column names.

Gives clean aliases.

Does not change data types.

Start with the query I gave for Key.Wrd4.
If that looks good in Parquet (names + values), we can write a similar one for any other tables you have.

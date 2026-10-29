-- mssql_gen_scripts.sql: writes a re-runnable schema script (Mode=schema) or seed script (Mode=seed) for the dbo schema of one database.
-- Run by mssql_gen_scripts.py; by hand: sqlcmd -I -f 65001 -y 0 -d <db> -v Mode=schema DisableTriggers=0 -i mssql_gen_scripts.sql
-- Mode=schema: tables (identity, computed and persisted columns, temporal period columns), primary keys, SYSTEM_VERSIONING after the keys,
--   other indexes (unique, included columns, filtered), defaults, check constraints, foreign keys, then views, procedures and triggers as CREATE OR ALTER.
-- Mode=seed: guarded inserts into empty tables only, parents before children, quotes doubled, IDENTITY_INSERT on.
--   DisableTriggers=1 wraps each insert in DISABLE TRIGGER ALL / ENABLE TRIGGER ALL.
-- Seed literal rules (each tested): money style 2, float and real style 3, datetimeoffset plain CONVERT (keeps the offset), xml and
--   hierarchyid and geography as text, sql_variant for int and nvarchar bases only; computed, rowversion and GENERATED ALWAYS columns skipped.
-- Not covered: other schemas than dbo, disabled check constraints, image/text/ntext/geometry, sequences, synonyms, user-defined types, columnstore and
--   full-text indexes, partitioning, history-table rows, sql_variant with other base types. Review the output before running it.
SET NOCOUNT ON;
CREATE TABLE #o (ord int IDENTITY, txt nvarchar(max));
DECLARE @nl nvarchar(2) = CHAR(13) + CHAR(10);
DECLARE @mode nvarchar(10) = N'$(Mode)';
DECLARE @colsep nvarchar(10) = N',' + @nl + N'  ';
DECLARE @disable int = $(DisableTriggers);

IF @mode = N'schema'
BEGIN
  INSERT #o (txt)
  SELECT N'IF OBJECT_ID(N''dbo.' + t.name + N''', N''U'') IS NULL' + @nl + N'CREATE TABLE [dbo].[' + t.name + N'] (' + @nl + N'  ' +
    STRING_AGG(CAST(
      CASE WHEN c.is_computed = 1 THEN N'[' + c.name + N'] AS ' + cc.definition + CASE WHEN cc.is_persisted = 1 THEN N' PERSISTED' ELSE N'' END
      ELSE N'[' + c.name + N'] ' +
        CASE ty.name
          WHEN N'nvarchar' THEN N'nvarchar(' + CASE WHEN c.max_length = -1 THEN N'max' ELSE CAST(c.max_length / 2 AS nvarchar(10)) END + N')'
          WHEN N'nchar' THEN N'nchar(' + CAST(c.max_length / 2 AS nvarchar(10)) + N')'
          WHEN N'varchar' THEN N'varchar(' + CASE WHEN c.max_length = -1 THEN N'max' ELSE CAST(c.max_length AS nvarchar(10)) END + N')'
          WHEN N'char' THEN N'char(' + CAST(c.max_length AS nvarchar(10)) + N')'
          WHEN N'varbinary' THEN N'varbinary(' + CASE WHEN c.max_length = -1 THEN N'max' ELSE CAST(c.max_length AS nvarchar(10)) END + N')'
          WHEN N'binary' THEN N'binary(' + CAST(c.max_length AS nvarchar(10)) + N')'
          WHEN N'decimal' THEN N'decimal(' + CAST(c.precision AS nvarchar(5)) + N',' + CAST(c.scale AS nvarchar(5)) + N')'
          WHEN N'numeric' THEN N'numeric(' + CAST(c.precision AS nvarchar(5)) + N',' + CAST(c.scale AS nvarchar(5)) + N')'
          WHEN N'datetime2' THEN N'datetime2(' + CAST(c.scale AS nvarchar(5)) + N')'
          WHEN N'time' THEN N'time(' + CAST(c.scale AS nvarchar(5)) + N')'
          WHEN N'datetimeoffset' THEN N'datetimeoffset(' + CAST(c.scale AS nvarchar(5)) + N')'
          ELSE ty.name END +
        CASE c.generated_always_type WHEN 1 THEN N' GENERATED ALWAYS AS ROW START' WHEN 2 THEN N' GENERATED ALWAYS AS ROW END' ELSE N'' END +
        CASE WHEN c.is_hidden = 1 THEN N' HIDDEN' ELSE N'' END +
        CASE WHEN c.is_identity = 1 THEN N' IDENTITY(' + CAST(IDENTITYPROPERTY(c.object_id, 'SeedValue') AS nvarchar(20)) + N',' + CAST(IDENTITYPROPERTY(c.object_id, 'IncrementValue') AS nvarchar(20)) + N')' ELSE N'' END +
        CASE WHEN c.is_nullable = 1 THEN N' NULL' ELSE N' NOT NULL' END END AS nvarchar(max)), @colsep) WITHIN GROUP (ORDER BY c.column_id)
    + ISNULL((SELECT @colsep + N'PERIOD FOR SYSTEM_TIME ([' + cs.name + N'], [' + ce.name + N'])' FROM sys.periods p JOIN sys.columns cs ON cs.object_id = p.object_id AND cs.column_id = p.start_column_id JOIN sys.columns ce ON ce.object_id = p.object_id AND ce.column_id = p.end_column_id WHERE p.object_id = t.object_id), N'')
    + @nl + N');'
  FROM sys.tables t
  JOIN sys.columns c ON c.object_id = t.object_id
  JOIN sys.types ty ON ty.user_type_id = c.user_type_id
  LEFT JOIN sys.computed_columns cc ON cc.object_id = c.object_id AND cc.column_id = c.column_id
  WHERE t.name NOT IN (N'sysdiagrams') AND t.temporal_type <> 1
  GROUP BY t.object_id, t.name, t.temporal_type, t.history_table_id ORDER BY t.name;

  INSERT #o (txt)
  SELECT N'IF OBJECT_ID(N''dbo.' + k.name + N''', N''PK'') IS NULL' + @nl + N'ALTER TABLE [dbo].[' + t.name + N'] ADD CONSTRAINT [' + k.name + N'] PRIMARY KEY CLUSTERED (' +
    (SELECT STRING_AGG(N'[' + c.name + N']' + CASE WHEN ic.is_descending_key = 1 THEN N' DESC' ELSE N'' END, N', ') WITHIN GROUP (ORDER BY ic.key_ordinal)
       FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
       WHERE ic.object_id = k.parent_object_id AND ic.index_id = k.unique_index_id) + N');'
  FROM sys.key_constraints k JOIN sys.tables t ON t.object_id = k.parent_object_id WHERE k.type = 'PK' AND t.temporal_type <> 1 ORDER BY t.name;

  INSERT #o (txt)
  SELECT N'IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE object_id = OBJECT_ID(N''dbo.' + t.name + N''') AND temporal_type = 2)' + @nl + N'ALTER TABLE [dbo].[' + t.name + N'] SET (SYSTEM_VERSIONING = ON (HISTORY_TABLE = [dbo].[' + OBJECT_NAME(t.history_table_id) + N']));'
  FROM sys.tables t WHERE t.temporal_type = 2 ORDER BY t.name;

  INSERT #o (txt)
  SELECT N'IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N''' + i.name + N''' AND object_id = OBJECT_ID(N''dbo.' + t.name + N'''))' + @nl +
    N'CREATE ' + CASE WHEN i.is_unique = 1 THEN N'UNIQUE ' ELSE N'' END + N'NONCLUSTERED INDEX [' + i.name + N'] ON [dbo].[' + t.name + N'] (' +
    (SELECT STRING_AGG(N'[' + c.name + N']' + CASE WHEN ic.is_descending_key = 1 THEN N' DESC' ELSE N'' END, N', ') WITHIN GROUP (ORDER BY ic.key_ordinal)
       FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
       WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 0) + N')' +
    ISNULL(N' INCLUDE (' + (SELECT STRING_AGG(N'[' + c.name + N']', N', ') FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
       WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 1) + N')', N'') +
    ISNULL(N' WHERE ' + i.filter_definition, N'') + N';'
  FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id WHERE i.is_primary_key = 0 AND i.type > 0 AND t.temporal_type <> 1 ORDER BY t.name, i.name;

  INSERT #o (txt)
  SELECT N'IF OBJECT_ID(N''dbo.' + d.name + N''', N''D'') IS NULL' + @nl + N'ALTER TABLE [dbo].[' + t.name + N'] ADD CONSTRAINT [' + d.name + N'] DEFAULT ' + d.definition + N' FOR [' + c.name + N'];'
  FROM sys.default_constraints d JOIN sys.tables t ON t.object_id = d.parent_object_id JOIN sys.columns c ON c.object_id = d.parent_object_id AND c.column_id = d.parent_column_id WHERE t.temporal_type <> 1 ORDER BY t.name, d.name;

  INSERT #o (txt)
  SELECT N'IF OBJECT_ID(N''dbo.' + k.name + N''', N''C'') IS NULL' + @nl + N'ALTER TABLE [dbo].[' + t.name + N'] WITH CHECK ADD CONSTRAINT [' + k.name + N'] CHECK ' + k.definition + N';'
  FROM sys.check_constraints k JOIN sys.tables t ON t.object_id = k.parent_object_id WHERE k.is_disabled = 0 AND t.temporal_type <> 1 ORDER BY t.name, k.name;

  INSERT #o (txt)
  SELECT N'IF OBJECT_ID(N''dbo.' + f.name + N''', N''F'') IS NULL' + @nl + N'ALTER TABLE [dbo].[' + t.name + N'] WITH CHECK ADD CONSTRAINT [' + f.name + N'] FOREIGN KEY (' +
    (SELECT STRING_AGG(N'[' + c.name + N']', N', ') WITHIN GROUP (ORDER BY fc.constraint_column_id) FROM sys.foreign_key_columns fc JOIN sys.columns c ON c.object_id = fc.parent_object_id AND c.column_id = fc.parent_column_id WHERE fc.constraint_object_id = f.object_id) +
    N') REFERENCES [dbo].[' + rt.name + N'] (' +
    (SELECT STRING_AGG(N'[' + c.name + N']', N', ') WITHIN GROUP (ORDER BY fc.constraint_column_id) FROM sys.foreign_key_columns fc JOIN sys.columns c ON c.object_id = fc.referenced_object_id AND c.column_id = fc.referenced_column_id WHERE fc.constraint_object_id = f.object_id) + N');'
  FROM sys.foreign_keys f JOIN sys.tables t ON t.object_id = f.parent_object_id JOIN sys.tables rt ON rt.object_id = f.referenced_object_id ORDER BY t.name, f.name;

  INSERT #o (txt)
  SELECT N'GO' + @nl + STUFF(m.definition, CHARINDEX(N'CREATE', m.definition), 6, N'CREATE OR ALTER') + @nl + N'GO'
  FROM sys.sql_modules m JOIN sys.objects o ON o.object_id = m.object_id WHERE o.type IN ('V', 'P', 'TR') AND o.name NOT LIKE N'sp[_]%diagram%' AND o.name <> N'fn_diagramobjects' ORDER BY CASE o.type WHEN 'V' THEN 1 WHEN 'P' THEN 2 ELSE 3 END, o.name;
END
ELSE
BEGIN
  DECLARE @t sysname, @sql nvarchar(max), @r nvarchar(max), @cols nvarchar(max), @lits nvarchar(max), @hasid bit, @hastrg bit;
  -- dependency depth: 0 for a table that references nothing, otherwise 1 + the deepest table it references (self references ignored)
  CREATE TABLE #depth (object_id int PRIMARY KEY, depth int NOT NULL);
  INSERT #depth SELECT object_id, 0 FROM sys.tables;
  DECLARE @changed int = 1, @iter int = 0;
  WHILE @changed > 0 AND @iter < 60
  BEGIN
    UPDATE d SET depth = x.nd
    FROM #depth d
    JOIN (SELECT fk.parent_object_id AS id, MAX(p.depth) + 1 AS nd
          FROM sys.foreign_keys fk JOIN #depth p ON p.object_id = fk.referenced_object_id
          WHERE fk.parent_object_id <> fk.referenced_object_id GROUP BY fk.parent_object_id) x ON x.id = d.object_id
    WHERE d.depth < x.nd;
    SET @changed = @@ROWCOUNT; SET @iter += 1;
  END
  DECLARE tc CURSOR FOR
    SELECT t.name FROM sys.tables t JOIN #depth dp ON dp.object_id = t.object_id WHERE t.name <> N'sysdiagrams' AND t.temporal_type <> 1
    ORDER BY dp.depth, t.name;
  OPEN tc; FETCH NEXT FROM tc INTO @t;
  WHILE @@FETCH_STATUS = 0
  BEGIN
    SELECT @cols = STRING_AGG(CAST(N'[' + c.name + N']' AS nvarchar(max)), N', ') WITHIN GROUP (ORDER BY c.column_id),
           @lits = STRING_AGG(CAST(
             CASE ty.name
               WHEN N'nvarchar' THEN N'ISNULL(N''N'' + CHAR(39) + REPLACE([' + c.name + N'], CHAR(39), CHAR(39) + CHAR(39)) + CHAR(39), N''NULL'')'
               WHEN N'nchar' THEN N'ISNULL(N''N'' + CHAR(39) + REPLACE([' + c.name + N'], CHAR(39), CHAR(39) + CHAR(39)) + CHAR(39), N''NULL'')'
               WHEN N'varchar' THEN N'ISNULL(CHAR(39) + REPLACE([' + c.name + N'], CHAR(39), CHAR(39) + CHAR(39)) + CHAR(39), N''NULL'')'
               WHEN N'char' THEN N'ISNULL(CHAR(39) + REPLACE([' + c.name + N'], CHAR(39), CHAR(39) + CHAR(39)) + CHAR(39), N''NULL'')'
               WHEN N'xml' THEN N'ISNULL(N''N'' + CHAR(39) + REPLACE(CONVERT(nvarchar(max), [' + c.name + N']), CHAR(39), CHAR(39) + CHAR(39)) + CHAR(39), N''NULL'')'
               WHEN N'uniqueidentifier' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(36), [' + c.name + N']) + CHAR(39), N''NULL'')'
               WHEN N'float' THEN N'ISNULL(CONVERT(varchar(50), [' + c.name + N'], 3), N''NULL'')'
               WHEN N'real' THEN N'ISNULL(CONVERT(varchar(50), [' + c.name + N'], 3), N''NULL'')'
               WHEN N'money' THEN N'ISNULL(CONVERT(nvarchar(50), [' + c.name + N'], 2), N''NULL'')'
               WHEN N'smallmoney' THEN N'ISNULL(CONVERT(nvarchar(50), [' + c.name + N'], 2), N''NULL'')'
               WHEN N'date' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(10), [' + c.name + N'], 23) + CHAR(39), N''NULL'')'
               WHEN N'time' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(16), [' + c.name + N'], 121) + CHAR(39), N''NULL'')'
               WHEN N'datetime2' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(27), [' + c.name + N'], 121) + CHAR(39), N''NULL'')'
               WHEN N'datetime' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(27), [' + c.name + N'], 121) + CHAR(39), N''NULL'')'
               WHEN N'smalldatetime' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(19), [' + c.name + N'], 120) + CHAR(39), N''NULL'')'
               WHEN N'datetimeoffset' THEN N'ISNULL(CHAR(39) + CONVERT(varchar(40), [' + c.name + N']) + CHAR(39), N''NULL'')'
               WHEN N'varbinary' THEN N'ISNULL(CONVERT(varchar(max), CONVERT(varbinary(max), [' + c.name + N']), 1), N''NULL'')'
               WHEN N'binary' THEN N'ISNULL(CONVERT(varchar(max), CONVERT(varbinary(max), [' + c.name + N']), 1), N''NULL'')'
               WHEN N'hierarchyid' THEN N'ISNULL(CHAR(39) + [' + c.name + N'].ToString() + CHAR(39), N''NULL'')'
               WHEN N'geography' THEN N'ISNULL(N''geography::STGeomFromText('' + CHAR(39) + [' + c.name + N'].STAsText() + CHAR(39) + N'','' + CAST([' + c.name + N'].STSrid AS nvarchar(10)) + N'')'', N''NULL'')'
               WHEN N'sql_variant' THEN N'ISNULL(CASE CONVERT(sysname, SQL_VARIANT_PROPERTY([' + c.name + N'], ''BaseType'')) WHEN ''int'' THEN N''CONVERT(sql_variant,'' + CONVERT(nvarchar(20), CONVERT(int, [' + c.name + N'])) + N'')'' WHEN ''nvarchar'' THEN N''CONVERT(sql_variant,N'' + CHAR(39) + REPLACE(CONVERT(nvarchar(4000), [' + c.name + N']), CHAR(39), CHAR(39) + CHAR(39)) + CHAR(39) + N'')'' END, N''NULL'')'
               ELSE N'ISNULL(CONVERT(nvarchar(50), [' + c.name + N']), N''NULL'')' END AS nvarchar(max)), N' + N'', '' + ') WITHIN GROUP (ORDER BY c.column_id),
           @hasid = MAX(CAST(c.is_identity AS int))
    FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    WHERE c.object_id = OBJECT_ID(N'dbo.' + @t) AND c.is_computed = 0 AND ty.name <> N'timestamp' AND c.generated_always_type = 0;
    SET @hastrg = CASE WHEN EXISTS (SELECT 1 FROM sys.triggers WHERE parent_id = OBJECT_ID(N'dbo.' + @t)) THEN 1 ELSE 0 END;
    SET @sql = N'SELECT @r = STRING_AGG(CAST(N''('' + ' + @lits + N' + N'')'' AS nvarchar(max)), N'',' + CHAR(13) + CHAR(10) + N' '') FROM [dbo].[' + @t + N']';
    SET @r = NULL;
    EXEC sp_executesql @sql, N'@r nvarchar(max) OUTPUT', @r OUTPUT;
    IF @r IS NOT NULL
      INSERT #o (txt) VALUES (N'IF NOT EXISTS (SELECT 1 FROM [dbo].[' + @t + N'])' + @nl + N'BEGIN' + @nl +
        CASE WHEN @hastrg = 1 AND @disable = 1 THEN N'  DISABLE TRIGGER ALL ON [dbo].[' + @t + N'];' + @nl ELSE N'' END +
        CASE WHEN @hasid = 1 THEN N'  SET IDENTITY_INSERT [dbo].[' + @t + N'] ON;' + @nl ELSE N'' END +
        N'  INSERT [dbo].[' + @t + N'] (' + @cols + N') VALUES' + @nl + N' ' + @r + N';' + @nl +
        CASE WHEN @hasid = 1 THEN N'  SET IDENTITY_INSERT [dbo].[' + @t + N'] OFF;' + @nl ELSE N'' END +
        CASE WHEN @hastrg = 1 AND @disable = 1 THEN N'  ENABLE TRIGGER ALL ON [dbo].[' + @t + N'];' + @nl ELSE N'' END + N'END' + @nl + N'GO');
    FETCH NEXT FROM tc INTO @t;
  END
  CLOSE tc; DEALLOCATE tc;
END
SELECT txt FROM #o ORDER BY ord;

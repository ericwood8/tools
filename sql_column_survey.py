"""Survey the column names of every user database on a SQL Server (Windows authentication, sqlcmd).

  python sql_column_survey.py --server HOST [--min-len 16] [--top 80] [--known WORD,WORD]

Prints how many distinct column names there are, how many are long when split into words, and the
most frequent long words, so an abbreviation list can be chosen from real names. --known lists words
that already have an abbreviation and are left out. Read only; the server name is an argument.
"""
import argparse, collections, re, subprocess, sys

QUERY = ("SET NOCOUNT ON; DECLARE @s nvarchar(max)=N''; "
         "SELECT @s += N'SELECT c.name FROM ['+name+N'].sys.columns c JOIN ['+name+N'].sys.tables t ON t.object_id=c.object_id UNION ALL ' "
         "FROM sys.databases WHERE database_id>4 AND state=0; "
         "SET @s = LEFT(@s, LEN(@s)-10); EXEC(@s);")

def split(n):
    return re.findall(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+', n.replace('_', ' '))

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--server', required=True)
    p.add_argument('--min-len', type=int, default=16)
    p.add_argument('--top', type=int, default=80)
    p.add_argument('--known', default='')
    a = p.parse_args()
    r = subprocess.run(['sqlcmd', '-S', a.server, '-E', '-h', '-1', '-W', '-Q', QUERY], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    names = sorted({l.strip() for l in r.stdout.splitlines() if l.strip()})
    known = {w.lower() for w in a.known.split(',') if w}
    long_names = [n for n in names if len(' '.join(split(n))) >= a.min_len]
    count = collections.Counter(w.lower() for n in long_names for w in set(split(n)) if len(w) >= 7 and w.lower() not in known)
    print(f'distinct names {len(names)}, long (>= {a.min_len} spaced) {len(long_names)}')
    print(' '.join(f'{w}:{c}' for w, c in count.most_common(a.top)))

main()

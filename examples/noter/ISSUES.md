# Issues (T3/T4 缺陷报告)

## FC1 durability (T3)
`add` 只写内存缓冲 (write-back 未实现): 文件已存在时新增笔记从不落盘,
新进程读文件看不到刚 add 的记录。接受: selfcheck.py --task durability 过。

## FC2 cache (T4)
`list` 结果缓存, add 之后缓存不失效 → 同一进程 add 后 list 仍是旧视图。
接受: selfcheck.py --task cache 过 (库层 in-process 直调, FC1 修复后独立可测)。
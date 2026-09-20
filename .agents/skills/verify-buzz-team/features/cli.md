# CLI 与适配器（S2）

用临时实例驱动 init、prepare、doctor、status；缺失实例、未知适配器、缺二进制和错误身份必须非零。Grok 与通用 ACP 各验证专用参数/环境；通用层不可强制注入 Grok 参数。真实实例 start/stop 只作用 Desktop，不独立启动第二套 harness；先检查空闲。workspace 以临时 Git 仓库验证合法创建和非法路径拒绝。

预检必须拒绝不可执行的适配器及无效 Desktop 应用；拒绝后真实绑定不变。buzz 消息入口遇到二进制摘要漂移时，在查询或发送前拒绝执行。

数据环境的容器、模式和值类型及保留变量名必须在绑定前校验；无效配置返回JSON错误且Desktop绑定不变。

适配器及数据环境中的已知凭据变量必须在doctor/bind前拒绝，不得回显值、写入Desktop或创建备份。受限身份在protected_home外也不能改写实例配置、薄入口、Desktop绑定和运行代码；包括符号链接替换，且正常身份工作区仍可写。

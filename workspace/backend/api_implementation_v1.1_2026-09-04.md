# pxiu 后端：Python FastAPI 进程生命周期管理

- 版本：v1.1
- 产出者：zhenhai（后端工程师）
- 日期：2026-09-04
- 前置：`workspace/architecture/api_contract_v1.yaml`（本任务与 API 契约无冲突，纯进程管理）

## 目标

Tauri 桌面应用自动拉起/关闭 FastAPI Python 后端进程（http://127.0.0.1:8765）。

1. Tauri 启动后，Python 服务自动运行
2. Tauri 关闭时，Python 进程被清理（不留孤儿进程）
3. 不影响开发体验（已有服务不重复启动）

## 方案选型

| 方案 | 说明 | 结论 |
|------|------|------|
| A. tauri-plugin-shell sidecar | 额外插件依赖 + 权限配置复杂，sidecar 需打包 Python 运行时 | 未选 |
| B. std::process::Command | 零额外依赖，直接 spawn `python3 -m uvicorn main:app`，精确控制生命周期 | **采用** |
| C. beforeDevCommand | 仅 dev 模式有效，生产构建无作用 | 辅助（dev 已由 npm run dev 驱动，Rust 端统一覆盖） |

**决策：方案 B。** 用 Rust `std::process::Command` 全模式（dev/prod）一致地管理 Python 进程，避免 plugin 打包复杂度与 beforeDevCommand 的 dev-only 局限。

## 修改文件

| 文件 | 变更 |
|------|------|
| `src-tauri/src/main.rs` | 新增 Python 进程 spawn/kill 逻辑 |
| `src-tauri/src/lib.rs` | 无变更（保留入口） |
| `src-tauri/tauri.conf.json` | 无变更（`beforeDevCommand: npm run dev` 已是正确 dev 配置） |
| `src-tauri/Cargo.toml` | 无变更（`std::process`/`std::net`/`std::sync` 均为标准库，零新依赖） |

## 实现逻辑（main.rs）

### 1) 端口探测 `is_server_running()`

```rust
fn is_server_running() -> bool {
    TcpStream::connect_timeout(
        &format!("{}:{}", SERVER_HOST, SERVER_PORT).parse().unwrap(),
        Duration::from_millis(500),
    ).is_ok()
}
```

- 连接 `127.0.0.1:8765`，超时 500ms。
- 若已占用（如开发者手动启动过服务），跳过 spawn，避免端口冲突与重复进程。

### 2) 路径解析 `resolve_server_path()`

- 优先相对可执行文件：`exe_dir/../../../server/main.py`（生产打包/`target/debug` 布局）。
- 回退相对当前工作目录：`../server/main.py`（dev 模式，cwd = `src-tauri/`）。
- 已验证：`src-tauri/../server/main.py` 存在 ✅，`server/.venv/bin/python3` 存在 ✅。

### 3) 进程启动 `spawn_python_server()`

```rust
let venv_python = server_dir.join(".venv/bin/python3");
let python_cmd = if venv_python.exists() { venv_python } else { PathBuf::from("python3") };

Command::new(&python_cmd)
    .arg("-m").arg("uvicorn")
    .arg("main:app")
    .arg("--host").arg(SERVER_HOST)
    .arg("--port").arg(SERVER_PORT.to_string())
    .current_dir(server_dir)   // main.py 所在目录，确保 main:app 可导入
    .spawn()
```

- **优先 venv**：`server/.venv/bin/python3`（项目虚拟环境，含 uvicorn/paddleocr 等依赖）。
- **回退系统**：无 venv 时用 PATH 上的 `python3`。
- `current_dir(server_dir)`：在 `server/` 下运行，`main:app` 直接可导入。

### 4) 进程清理 `kill_python_server()`

```rust
if let Ok(None) = child.try_wait() {
    child.kill()?;
    child.wait();   // reap 僵尸进程
}
```

- `try_wait()` 先检查进程是否已退出，避免对死进程 kill 报错。
- `wait()` 回收资源，防僵尸。

### 5) 生命周期接线

```rust
let python_child = spawn_python_server().map(Mutex::new);

let app = tauri::Builder::default()
    .build(tauri::generate_context!())
    .expect("error while building tauri application");

app.run(move |_app_handle, event| {
    use tauri::RunEvent;
    if let RunEvent::Exit = event {
        if let Some(child) = &python_child {
            if let Ok(mut guard) = child.lock() {
                kill_python_server(&mut guard);
            }
        }
    }
});
```

- **spawn**：`main()` 开头即启动 Python。
- **kill**：挂载到 `app.run()` 的 `RunEvent::Exit`。
  - Tauri 2 的 `App::run` 在退出时直接 `std::process::exit`，`RunEvent::Exit` 在进程退出**前**触发。
  - 覆盖所有退出路径：正常关窗、`AppHandle::exit`、终端杀进程。
  - `Mutex<Child>` 使闭包间跨事件共享可变进程句柄。

## 可靠性与边界（对抗式审查）

| 边界场景 | 处理 |
|----------|------|
| 端口已被占用（服务已在跑） | 端口探测跳过 spawn，不重复进程 |
| venv 不存在 | 回退 PATH 上 `python3` |
| 关窗前 Python 已崩溃退出 | `try_wait()` 检测已退出，kill 幂等 |
| 异常退出（未走正常关窗） | `RunEvent::Exit` 仍触发（Tauri 官方确认 kill 时触发） |
| macOS 子进程残留 | `kill + wait` 同步回收 |
| dev 模式下 Cargo 热重载 | 仅新增 spawn；重复 Cargo 启动会被端口探测拦截 |

**最可能被挑战的假设**：`RunEvent::Exit` 一定在 `std::process::exit` 前触发。
- 依据：Tauri 官方 `App::run`/`run_return` 文档确认 `Exit` 事件在退出前回调。
- 降级：若个别平台时机异常，进程仍可被端口占用检测到的下次启动/系统回收，且 `kill+wait` 已是尽力清理。

## 待办标注

- 本机无 `cargo`/rustup 工具链，**未能执行 `cargo build` 编译验证**。代码已按 Tauri 2 官方 API 逐项校验（`Builder::build`、`App::run`、`RunEvent::Exit`、`Mutex<Child>`）。
- 前端 `pxiu-app/package.json` 未配置 `test` script，**无 `npm test` 可运行**。
- 建议在有 Rust 工具链的环境执行 `cargo build` 与启动验证后，再进入 shouye 测试 / dana 审查。

# 全帧服务接口约定（待组员实现）

此工作流调用外部服务，不包含服务的部署、音视频解码或模型调用；云端工作流页面显示已发布，但尚未验证与真实全帧服务的端到端运行。部署方应先完成接口、安全及端到端测试。服务端的报告必须真实基于全帧检测、实际音频和评分，避免因模型失败或不完整而误报通过。

项目内 `full_frame_pipeline.py` 是可供服务实现参考的本地处理原型；任务接口、鉴权、托管及端到端验证仍待实现，不能将原型视为已部署服务。

在 Dify 设置环境变量 `FULL_FRAME_BASE_URL`（HTTPS，服务根地址或以 `/api` 结尾）和 `FULL_FRAME_API_KEY`（Secret）。密钥只配置在 Dify 和服务端，勿写入 YAML。服务应验证 bearer token，使用 HTTPS；限制视频大小、时长、任务并发，验证视频 URL 并防止服务端请求伪造。Dify 的上传文件 URL 需能被服务读取且在任务下载完成前有效，部署方须验证网络、时效和权限，不能假设所有 Dify 文件 URL 都公开可达。视频、音频和结果均须按团队的隐私策略处理。

## 提交任务

`POST {FULL_FRAME_BASE_URL}/jobs`

请求头：`Authorization: Bearer <FULL_FRAME_API_KEY>`，`Content-Type: application/json`。请求体如下（脚本和规则仅作对照，不能当实际视频证据）：

```json
{"video_url":"https://...","script":"","rules":"","language":"en-US"}
```

接收后迅速返回 HTTP 200、201 或 202，响应 `{"job_id":"唯一任务编号"}`。编号只能包含字母、数字、下划线、连字符，长度 1～100。服务应持久化任务状态并避免重复执行。超时或错误不视为完成。

## 查询任务

`GET {FULL_FRAME_BASE_URL}/jobs/{job_id}`，同样使用 bearer token。返回 HTTP 200 与以下任一种 JSON：

```json
{"status":"pending"}
{"status":"running"}
{"status":"failed"}
{"status":"succeeded","result":{"report":"## 评分\n...","verdict":"通过","total":85.0,"coverage_complete":true}}
```

`succeeded` 表示生成了完整的最终处理结果，不表示视频合格；`result.verdict` 只能为 `通过` 或 `转人工`。`report` 是服务生成的完整文本。`total` 为综合评分（无法评分用 `null`），`coverage_complete` 为布尔值。服务端必须在逐帧解码与检测均成功、全部七项有足够证据、总分至少 80 且未检出规则内风险时才输出 `通过`；检测失败、评分证据不足时不得输出通过。违规或总分低于 80 应转人工。服务还应保存覆盖数量和失败帧等明细供排查，并在报告明确 AI 检测可能漏识别。工作流对通过结果额外检查 `coverage_complete=true`、`total` 为 80～100 的有限数值；这只能检查服务的声明，无法独立证明服务确实检测每帧。

工作流每 10 秒查询一次，最多 100 次，受 Dify 实际节点超时、总运行时间和平台配额约束。失败、响应格式不符、未配置或轮询超时均显示未完成/失败，不输出合格评分；超时不代表后台任务停止。正式接入前须测试目标环境对长任务的实际限制；若超过平台限制，应改为异步查询页面或回调机制，而不能把未完成当作通过。避免自动重复提交造成重复计费。

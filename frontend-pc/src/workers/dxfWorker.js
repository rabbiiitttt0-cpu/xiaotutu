// dxf-viewer 解析 worker：Load({workerFactory}) 创建的 Worker 脚本必须
// 只做「import + SetupWorker()」这一件事（见 dxf-viewer 文档 DxfViewer.SetupWorker）
import { DxfViewer } from 'dxf-viewer'

DxfViewer.SetupWorker()

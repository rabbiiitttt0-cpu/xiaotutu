<template>
  <div class="drawing-page">
    <!-- 返回按钮 -->
    <div class="page-header"><h2>识图助手</h2></div>

    <div class="drawing-layout">
      <!-- 左侧：图纸信息 -->
    <el-card shadow="never" class="drawing-left-card" :class="{ open: leftPanelOpen }">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>图纸上传</span>
          <el-button class="mobile-toggle" size="small" text type="primary" @click="leftPanelOpen = !leftPanelOpen">
            {{ leftPanelOpen ? '收起 ▲' : '展开 ▼' }}
          </el-button>
        </div>
      </template>

      <!-- 一键清空（左上角）：清空已上传文件+图纸集+预览+对话 -->
      <div style="display: flex; justify-content: flex-start; margin-bottom: 8px">
        <el-popconfirm title="清空全部已上传文件和图纸集？" width="220" @confirm="doClear">
          <template #reference>
            <el-button size="small" type="danger" plain :disabled="!fileList.length && !sheets.length && !fileId">
              <el-icon><Delete /></el-icon> 清空已上传
            </el-button>
          </template>
        </el-popconfirm>
      </div>

      <!-- 图纸来源：本地上传（实时解析）| 项目图纸（预处理秒开） -->
      <el-radio-group v-model="sourceMode" size="small" style="width: 100%; margin-bottom: 10px" @change="onSourceModeChange">
        <el-radio-button value="upload" style="width: 50%">本地上传</el-radio-button>
        <el-radio-button value="project" style="width: 50%">项目图纸</el-radio-button>
      </el-radio-group>

      <!-- ==================== 项目图纸模式 ==================== -->
      <template v-if="sourceMode === 'project'">
        <el-select
          v-model="activeProjectId" placeholder="选择项目" style="width: 100%"
          @change="onProjectChange"
        >
          <el-option v-for="p in myProjects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-empty
          v-if="!myProjects.length" description="您还未加入任何项目，请联系管理员" :image-size="50"
        />

        <template v-else>
          <!-- 选图纸 / 图纸集 切换 -->
          <el-radio-group v-model="projPickMode" size="small" style="width: 100%; margin-top: 10px">
            <el-radio-button value="browse" style="width: 50%">选图纸</el-radio-button>
            <el-radio-button value="sets" style="width: 50%">图纸集</el-radio-button>
          </el-radio-group>

          <!-- 图纸集模式：点击整组载入（由管理员预设） -->
          <template v-if="projPickMode === 'sets'">
            <div style="margin-top: 8px">
              <el-empty v-if="!projSets.length" description="暂无图纸集，请联系管理员在项目管理中预设" :image-size="40" />
              <el-tag
                v-for="s in projSets" :key="s.id" type="warning" effect="plain"
                style="margin: 0 6px 6px 0; cursor: pointer"
                @click="applySet(s)"
              >
                {{ s.name }}（{{ s.drawing_ids.length }} 张）
              </el-tag>
            </div>
          </template>

          <!-- 选图纸模式：按压缩包目录结构分组折叠 -->
          <template v-else>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px">
              <span style="font-size: 13px; color: #606266">项目图纸</span>
              <el-switch
                v-model="showAllDrawings" active-text="全部" inactive-text="常用"
                inline-prompt
              />
            </div>
            <div style="max-height: 240px; overflow-y: auto; margin-top: 4px">
              <el-checkbox-group v-model="selectedDrawingIds" style="display: flex; flex-direction: column">
                <template v-for="g in drawingGroups" :key="g.key">
                  <div class="dg-head" @click="toggleGroup(g)">
                    <el-icon :size="13" style="color: #e6a23c"><Folder /></el-icon>
                    <span style="font-weight: 600">{{ g.name }}</span>
                    <span style="color: #909399; font-size: 12px">（{{ g.files.length }} 张）</span>
                    <el-icon :size="12" style="margin-left: auto; color: #909399">
                      <ArrowDown v-if="!collapsedGroups[g.key]" /><ArrowRight v-else />
                    </el-icon>
                  </div>
                  <template v-if="!collapsedGroups[g.key]">
                    <el-checkbox v-for="f in g.files" :key="f.id" :value="f.id" style="padding-left: 16px">
                      <span style="font-size: 13px">{{ f.filename }}</span>
                      <el-tag v-if="f.is_frequent" size="small" type="warning" style="margin-left: 4px">常用</el-tag>
                    </el-checkbox>
                  </template>
                </template>
                <el-empty
                  v-if="!drawingGroups.length"
                  :description="showAllDrawings ? '项目暂无已处理图纸' : '暂无常用图纸，切到「全部」查看'"
                  :image-size="40"
                />
              </el-checkbox-group>
            </div>
          </template>

          <div style="display: flex; gap: 8px; margin-top: 10px">
            <el-button
              type="primary" style="flex: 1" :loading="projApplying"
              :disabled="!selectedDrawingIds.length" @click="applyProjectDrawings(true)"
            >
              开始问答（已选 {{ selectedDrawingIds.length }} 张）
            </el-button>
          </div>
          <div style="font-size: 12px; color: #909399; margin-top: 6px">
            预处理图纸无需等待解析；会话（含对话上下文）保留 5 天
          </div>
        </template>
      </template>

      <!-- ==================== 本地上传模式 ==================== -->
      <template v-else>
      <el-upload
        ref="uploadRef"
        drag
        multiple
        :auto-upload="false"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
        :file-list="fileList"
        accept=".dxf,.dwg,.pdf"
        :disabled="uploading"
      >
        <el-icon style="font-size: 40px; color: #909399"><Upload /></el-icon>
        <div>拖拽CAD图纸到此处，或<em>点击上传</em></div>
        <template #tip>
          <div style="color: #909399; font-size: 12px">支持 .dxf / .dwg / .pdf，可多选；已解析文件保留在列表中，再次解析只处理新增</div>
        </template>
      </el-upload>

      <el-button
        type="primary"
        style="width: 100%; margin-top: 12px"
        @click="uploadFile"
        :loading="uploading"
        :disabled="!pendingCount"
      >
        {{ uploading ? '解析中...' : pendingCount > 1 ? `解析图纸（新增 ${pendingCount} 张）` : '解析图纸' }}
      </el-button>
      </template>

      <!-- 图纸集面板（一套多图，>3张问答自动路由选图） -->
      <div v-if="sheets.length" style="margin-top: 16px">
        <el-divider content-position="left">图纸集（{{ sheets.length }} 张）</el-divider>
        <div style="max-height: 240px; overflow-y: auto">
          <div
            v-for="s in sheets" :key="s.file_id"
            :class="['sheet-item', { active: s.file_id === activeSheetId }]"
            @click="selectSheet(s.file_id)"
          >
            <el-tag size="small" :type="s.doc_type === 'pdf' ? 'warning' : 'success'" style="flex-shrink: 0">
              {{ s.doc_type === 'pdf' ? 'PDF' : 'CAD' }}
            </el-tag>
            <span class="sheet-name" :title="s.filename">{{ s.filename }}</span>
          </div>
        </div>
        <div style="font-size: 12px; color: #909399; margin-top: 6px">点击图幅可单独预览；问答自动选取相关图幅</div>
      </div>

      <!-- 图纸信息（单图模式显示；图纸集模式上面板代替） -->
      <div v-if="drawingInfo && !sheets.length" style="margin-top: 16px">
        <el-divider content-position="left">图纸概况</el-divider>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="文件名">{{ drawingInfo.filename }}</el-descriptions-item>
          <el-descriptions-item v-if="drawingInfo.total_entities" label="图层数">{{ drawingInfo.layer_count }}</el-descriptions-item>
          <el-descriptions-item v-if="drawingInfo.total_entities" label="实体总数">{{ drawingInfo.total_entities }}</el-descriptions-item>
        </el-descriptions>

        <!-- DXF 专属区块（PDF 图纸无图层/实体概念，隐藏） -->
        <template v-if="drawingInfo.layers && drawingInfo.layers.length">
          <el-divider content-position="left">图层列表</el-divider>
          <el-table :data="drawingInfo.layers" stripe size="small" max-height="200">
            <el-table-column prop="name" label="图层名" />
            <el-table-column label="颜色" width="60">
              <template #default="{ row }">
                <div :style="{ width: '16px', height: '16px', background: layerColor(row.color), border: '1px solid #ccc', borderRadius: '2px' }" />
              </template>
            </el-table-column>
            <el-table-column label="状态" width="60">
              <template #default="{ row }">
                <el-tag :type="row.is_on ? 'success' : 'info'" size="small">{{ row.is_on ? '开' : '关' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>

          <el-divider content-position="left">实体统计</el-divider>
          <div style="display: flex; flex-wrap: wrap; gap: 8px">
            <el-tag v-for="(count, type) in drawingInfo.entity_counts" :key="type" size="small">
              {{ type }}: {{ count }}
            </el-tag>
          </div>
        </template>

        <template v-if="drawingInfo.text_annotations && drawingInfo.text_annotations.length > 0">
          <el-divider content-position="left">文字标注</el-divider>
          <div style="max-height: 200px; overflow-y: auto; font-size: 12px; color: #666">
            <div v-for="(t, i) in drawingInfo.text_annotations.slice(0, 20)" :key="i" style="margin-bottom: 4px">
              <el-tag size="small" type="info">{{ t.layer }}</el-tag>
              {{ t.text }}
            </div>
          </div>
        </template>
      </div>

      <!-- 底部功能行：钟表按钮呼出历史会话记录（覆盖右侧主区） -->
      <div class="clock-row">
        <button
          class="clock-btn" :class="{ active: historyVisible }"
          title="历史会话记录"
          @click="historyVisible = !historyVisible; if (historyVisible) loadHistory()"
        >
          <el-icon><Clock /></el-icon>
        </button>
        <span class="clock-label">历史会话记录（{{ historySessions.length }} 条）</span>
      </div>
    </el-card>

    <!-- 右侧：功能区 -->
    <div class="drawing-right-col" style="flex: 1; display: flex; flex-direction: column; gap: 16px; min-width: 0; overflow: hidden; position: relative">
    <!-- 图纸预览（主视区，滚轮缩放+拖动+图幅切换；高度可拖拽调节） -->
    <el-card shadow="never" class="preview-card" :style="{ height: previewRatio + '%', flex: 'none' }">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px">
          <div style="display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1">
            <span style="flex-shrink: 0">图纸预览</span>
            <!-- 图幅切换器（多图时显示） -->
            <template v-if="sheets.length > 1">
              <el-button size="small" circle :disabled="sheetIdx <= 0" @click="switchSheet(-1)">
                <el-icon><ArrowLeft /></el-icon>
              </el-button>
              <el-select
                :model-value="activeSheetId" size="small" style="min-width: 0; flex: 1"
                @change="selectSheet"
              >
                <el-option v-for="s in sheets" :key="s.file_id" :label="s.filename" :value="s.file_id" />
              </el-select>
              <el-button size="small" circle :disabled="sheetIdx >= sheets.length - 1" @click="switchSheet(1)">
                <el-icon><ArrowRight /></el-icon>
              </el-button>
            </template>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0">
            <!-- 截图提问：框选图纸局部，针对该区域提问 -->
            <el-tooltip content="框选图纸局部，针对该区域提问（如：这样的桩还有多少？）" placement="bottom">
              <el-button
                v-if="previewUrls.length && previewMode !== 'dxf'" size="small" round
                :type="snipMode ? 'primary' : 'info'" plain
                @click="snipMode = !snipMode"
              >
                <el-icon><Crop /></el-icon> {{ snipMode ? '框选中…' : '截图提问' }}
              </el-button>
            </el-tooltip>
            <!-- 预览格式切换：PNG 位图 / DXF 矢量(dxf-viewer WebGL)
                 （SVG 已移除：matplotlib 出图把细线糊成等粗，观感差于位图） -->
            <el-radio-group
              v-if="dxfUrl" size="small" :model-value="previewMode"
              @update:model-value="previewMode = $event"
            >
              <el-radio-button value="png">PNG</el-radio-button>
              <el-radio-button v-if="dxfUrl" value="dxf">DXF 矢量</el-radio-button>
            </el-radio-group>
            <span v-if="previewUrls.length" style="font-size: 12px; color: #67c23a">
              <el-icon><View /></el-icon> 视觉模式已启用
            </span>
          </div>
        </div>
      </template>
      <div v-if="previewUrls.length" class="preview-body">
        <!-- DXF 矢量模式：dxf-viewer WebGL 画布（自带拖动/滚轮缩放/触控） -->
        <div v-if="previewMode === 'dxf'" class="dxf-host" ref="dxfHostRef">
          <div class="pz-hint dxf-hint">
            <span>左键拖动 · 滚轮缩放 · 触控双指</span>
          </div>
          <div v-if="dxfLoading" class="dxf-loading">DXF 矢量解析中…（大图约数秒）</div>
        </div>
        <!-- 自绘缩放拖动容器：滚轮缩放、按住拖动、双击复位 -->
        <div
          v-else
          ref="pzRef" class="pz-container" :class="{ dragging: isDragging, snipping: snipMode }"
          @wheel.prevent="onZoom"
          @mousedown="startDrag" @mousemove="onDrag" @mouseup="endDrag" @mouseleave="endDrag"
          @dblclick="snipMode ? null : resetZoom()"
          @touchstart.prevent="onTouchStart" @touchmove.prevent="onTouchMove" @touchend="onTouchEnd"
        >
          <img
            :src="displaySrc" class="pz-image" draggable="false"
            :style="{ transform: `translate(calc(-50% + ${pan.x}px), calc(-50% + ${pan.y}px)) scale(${scale})` }"
          />
          <!-- 框选矩形 -->
          <div v-if="snipRect" class="snip-rect" :style="snipRectStyle" />
          <!-- 多页翻页（PDF 多页 / 图框切片） -->
          <div v-if="pageTotal > 1" class="pz-pager">
            <el-button size="small" circle :disabled="pageIdx <= 0" @click.stop="pageIdx--; resetZoom()">
              <el-icon><ArrowLeft /></el-icon>
            </el-button>
            <span>{{ pageIdx + 1 }} / {{ pageTotal }}</span>
            <el-button size="small" circle :disabled="pageIdx >= pageTotal - 1" @click.stop="pageIdx++; resetZoom()">
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
          <div class="pz-hint">
            <span class="hint-desktop">滚轮缩放 · 按住拖动 · 双击复位</span>
            <span class="hint-mobile">双指缩放 · 单指拖动</span>
            <button class="reset-btn" @click.stop="resetZoom">{{ Math.round(scale * 100) }}%</button>
          </div>
        </div>
      </div>
      <div v-else class="preview-empty">
        <el-icon style="font-size: 48px"><Picture /></el-icon>
        <div style="margin-top: 12px">上传图纸后，此处显示渲染预览（滚轮缩放、拖动查看）</div>
      </div>
    </el-card>

    <!-- 可拖拽分隔条：按住调节 预览↕问答 比例，双击复位 55% -->
    <div
      class="split-divider" title="按住拖动调整比例，双击复位"
      @mousedown="startSplit" @touchstart.prevent="startSplit" @dblclick="previewRatio = 55"
    >
      <span class="split-grip" />
    </div>

    <!-- 问答/材料/交底（下移） -->
    <el-card shadow="never" style="flex: 1; display: flex; flex-direction: column; overflow: hidden; min-height: 0">
      <el-tabs v-model="rightTab" style="height: 100%; display: flex; flex-direction: column" class="drawing-tabs">
        <!-- Tab1: 图审问答 -->
        <el-tab-pane label="图审问答" name="chat">
          <!-- 消息列表 -->
          <div ref="chatContainer" class="chat-messages">
            <div v-if="messages.length === 0" style="text-align: center; color: #909399; padding: 60px 0">
              <el-icon style="font-size: 48px"><ChatDotRound /></el-icon>
              <div style="margin-top: 12px">上传DXF图纸后，可以在这里提问</div>
              <div style="margin-top: 8px; font-size: 12px">
                例如：这张图一共有多少个图层？ / 图中有哪些文字标注？
              </div>
            </div>

            <div v-for="(msg, i) in messages" :key="i" :style="msgStyle(msg)">
              <div :class="['chat-bubble', msg.role]">
                <div style="font-size: 12px; color: #909399; margin-bottom: 4px">
                  {{ msg.role === 'user' ? '我' : '识图助手' }}
                </div>
                <div style="white-space: pre-wrap; line-height: 1.6">{{ msg.content }}</div>
                <div v-if="msg.referenced && msg.referenced.length" style="margin-top: 6px; font-size: 12px; color: #909399">
                  参考图幅：<el-tag v-for="r in msg.referenced" :key="r.file_id" size="small" type="info" style="margin-right: 4px">{{ r.filename }}</el-tag>
                </div>
              </div>
            </div>

            <div v-if="chatLoading" style="padding: 12px 16px">
              <el-icon class="is-loading" style="font-size: 20px"><Loading /></el-icon>
              <span style="margin-left: 8px; color: #909399">分析中...</span>
            </div>
          </div>

          <!-- 输入框 -->
          <div class="chat-input-area">
            <!-- 框选截图 chip -->
            <div v-if="snipBlobUrl" class="snip-chip">
              <img :src="snipBlobUrl" alt="框选截图" />
              <span>已框选局部截图，提问将针对该区域</span>
              <el-icon style="cursor: pointer" @click="snipBlobUrl = ''"><Close /></el-icon>
            </div>
            <div class="chat-input-wrapper">
              <el-input
                v-model="question"
                type="textarea"
                :rows="2"
                placeholder="请输入关于图纸的问题（可点上方「截图提问」框选局部，或点话筒语音输入）..."
                @keydown.enter.ctrl="sendQuestion"
                :disabled="!hasContext || chatLoading"
                resize="none"
                class="chat-textarea"
              />
              <el-tooltip content="语音输入（说话后再次点击结束）" placement="top">
                <el-button
                  class="voice-btn" :class="{ recording: recognizing }"
                  :type="recognizing ? 'danger' : 'info'" circle plain
                  :loading="voiceUploading"
                  :disabled="!hasContext || chatLoading"
                  @click="toggleVoice"
                >
                  <el-icon v-if="!voiceUploading"><Microphone /></el-icon>
                </el-button>
              </el-tooltip>
              <el-button
                class="chat-send-btn"
                type="primary"
                circle
                :loading="chatLoading"
                :disabled="!hasContext || !question.trim()"
                @click="sendQuestion"
              >
                <el-icon><Promotion /></el-icon>
              </el-button>
            </div>
            <span class="chat-hint">Ctrl+Enter 发送</span>
          </div>
        </el-tab-pane>

        <!-- Tab2: 材料表 -->
        <el-tab-pane label="材料表" name="materials">
          <div style="padding: 8px 0">
            <div v-if="!hasContext" style="text-align: center; color: #909399; padding: 60px 0">
              <el-icon style="font-size: 48px"><List /></el-icon>
              <div style="margin-top: 12px">请先上传图纸</div>
            </div>

            <template v-else>
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
                <span style="font-weight: 500">图纸材料清单</span>
                <el-button type="primary" size="small" @click="extractMaterials" :loading="materialsLoading">
                  {{ materials.length > 0 ? '重新提取' : '提取材料表' }}
                </el-button>
              </div>

              <div v-if="materialsLoading" style="text-align: center; padding: 40px 0">
                <el-icon class="is-loading" style="font-size: 32px"><Loading /></el-icon>
                <div style="margin-top: 12px; color: #909399">正在分析图纸提取材料信息...</div>
              </div>

              <el-empty v-else-if="materials.length === 0" description="点击「提取材料表」开始分析" :image-size="60" />

              <template v-else>
                <el-table :data="materials" stripe size="small" max-height="calc(100vh - 360px)">
                  <el-table-column type="index" label="#" width="50" />
                  <el-table-column prop="name" label="材料名称" min-width="120" />
                  <el-table-column prop="spec" label="规格型号" min-width="120" show-overflow-tooltip />
                  <el-table-column prop="unit" label="单位" width="70" />
                  <el-table-column prop="layer" label="来源图层" width="120" show-overflow-tooltip />
                  <el-table-column prop="note" label="备注" min-width="100" show-overflow-tooltip />
                </el-table>

                <div style="margin-top: 12px; text-align: right">
                  <el-button size="small" @click="exportMaterials">
                    <el-icon><Download /></el-icon> 导出材料表
                  </el-button>
                </div>
              </template>
            </template>
          </div>
        </el-tab-pane>

        <!-- Tab3: 快速交底 -->
        <el-tab-pane label="快速交底" name="briefing">
          <div style="padding: 8px 0">
            <div v-if="!hasContext" style="text-align: center; color: #909399; padding: 60px 0">
              <el-icon style="font-size: 48px"><Document /></el-icon>
              <div style="margin-top: 12px">请先上传图纸</div>
            </div>

            <template v-else>
              <el-form label-position="top" style="margin-bottom: 12px">
                <el-form-item label="项目名称">
                  <el-input v-model="briefingProjectName" placeholder="请输入项目名称（可选）" />
                </el-form-item>
                <el-form-item label="补充信息">
                  <el-input v-model="briefingExtraInfo" type="textarea" :rows="2" placeholder="补充施工要求、特殊条件等信息（可选）" />
                </el-form-item>
              </el-form>

              <el-button type="primary" style="width: 100%" @click="generateBriefing" :loading="briefingLoading">
                <el-icon><Document /></el-icon> {{ briefingContent ? '重新生成' : '生成交底文件' }}
              </el-button>

              <div v-if="briefingLoading" style="text-align: center; padding: 40px 0">
                <el-icon class="is-loading" style="font-size: 32px"><Loading /></el-icon>
                <div style="margin-top: 12px; color: #909399">正在生成图纸交底文件...</div>
              </div>

              <div v-if="briefingContent" style="margin-top: 16px">
                <el-divider content-position="left">交底文件内容</el-divider>
                <div style="max-height: calc(100vh - 520px); overflow-y: auto; padding: 12px; background: #f5f7fa; border-radius: 4px; white-space: pre-wrap; line-height: 1.8; font-size: 13px">
                  {{ briefingContent }}
                </div>
                <div style="margin-top: 12px; text-align: right">
                  <el-button size="small" @click="exportBriefing">
                    <el-icon><Download /></el-icon> 导出交底文件
                  </el-button>
                </div>
              </div>
            </template>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 历史会话记录覆盖层（点击左侧钟表按钮弹出，覆盖预览与问答区） -->
    <div v-if="historyVisible" class="history-overlay">
      <div class="history-overlay-header">
        <span>历史会话记录<span style="font-size: 12px; color: #909399; margin-left: 8px">共 {{ historySessions.length }} 条</span></span>
        <el-button size="small" circle @click="historyVisible = false">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
      <el-empty v-if="historySessions.length === 0" description="暂无会话记录" :image-size="60" />
      <el-table v-else :data="historySessions" stripe size="small" max-height="calc(100% - 60px)" highlight-current-row @row-click="loadSession">
        <el-table-column :label="sourceMode === 'project' ? '会话' : '图纸文件'" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.filename || row.title }}</template>
        </el-table-column>
        <el-table-column v-if="sourceMode !== 'project'" label="图层" width="70">
          <template #default="{ row }">{{ row.layer_count }}</template>
        </el-table-column>
        <el-table-column v-if="sourceMode !== 'project'" label="实体" width="70">
          <template #default="{ row }">{{ row.total_entities }}</template>
        </el-table-column>
        <el-table-column label="对话数" width="80">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.message_count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="165" />
        <el-table-column v-if="sourceMode === 'project'" prop="expires_at" label="保留至" width="165" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <div style="display: flex; gap: 4px; align-items: center">
              <el-button size="small" @click.stop="loadSession(row); historyVisible = false">查看</el-button>
              <el-popconfirm title="确定删除该会话？" @confirm.stop="deleteSession(row.session_id || row.id)">
                <template #reference>
                  <el-button size="small" type="danger" plain @click.stop>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    </div>
    </div>

    <TutorialOverlay ref="tutorialRef" page-key="drawing" :steps="tutorialSteps" />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { drawing as drawingApi, projects as projectsApi, chatErrMsg } from '../api'
import { WavRecorder } from '../utils/wavRecorder'
import TutorialOverlay from '../components/TutorialOverlay.vue'

const tutorialRef = ref(null)
const tutorialSteps = [
  { title: '识图助手', icon: 'MapLocation', color: '#409eff', content: '上传工程图纸（.dxf/.dwg/.pdf），AI智能解读图纸内容', detail: '系统自动解析图层、实体和文字标注信息。上传后AI会自动生成图纸概述，帮助您快速了解图纸内容。' },
  { title: '图审问答', icon: 'ChatDotRound', color: '#67c23a', content: '在右侧对话框中向AI提问图纸相关问题', detail: '可以询问图层信息、实体数量、文字标注、材料清单等任何关于图纸的问题。使用Ctrl+Enter发送。' },
  { title: '材料表与交底', icon: 'List', color: '#e6a23c', content: '切换Tab可提取材料表或生成图纸交底', detail: '材料表：自动从图纸中提取材料信息，支持导出CSV；快速交底：根据图纸内容自动生成施工交底文件，可导出为文本文件。' },
]

const fileList = ref([])   // {uid,name,size,raw,uploaded,file_id} 已解析的 uploaded=true
const uploadRef = ref(null)
const leftPanelOpen = ref(false)  // 手机下上传/图纸集面板默认收起，看图+问答占满屏
const uploading = ref(false)

// 待解析（新增未上传）文件数
const pendingCount = computed(() => fileList.value.filter(f => !f.uploaded).length)
const drawingInfo = ref(null)
const fileId = ref('')
const sessionId = ref('')

// 图纸集（一套多图）
const setId = ref('')
const sheets = ref([])
const activeSheetId = ref('')

// 是否有可用图纸上下文（图纸集或单图；项目模式应用图纸后同样会设置二者之一）
const hasContext = computed(() => !!setId.value || !!fileId.value)
// ===== 项目图纸模式：状态 =====

const sourceMode = ref('upload')        // upload 本地上传 | project 项目图纸
const myProjects = ref([])              // 我参与的项目
const activeProjectId = ref(null)       // 当前选中项目
const projTree = ref([])                // 项目图纸目录树（drawings-tree）
const projSets = ref([])                // 项目图纸集（管理员预设）
const projPickMode = ref('browse')      // browse 选图纸 | sets 图纸集
const selectedDrawingIds = ref([])      // 勾选的项目图纸
const collapsedGroups = ref({})         // 折叠的分组 key → true
const showAllDrawings = ref(false)      // 常用（默认）| 全部
const projApplying = ref(false)         // 开始问答加载中
const projSessionId = ref(0)            // 项目会话 id（0=未建）

// 目录树拍平为分组：根目录文件 + 各文件夹（含多级路径名）一组，保持压缩包结构
const drawingGroups = computed(() => {
  const groups = []
  const rootFiles = []
  const keep = (f) => showAllDrawings.value || f.is_frequent
  const walk = (nodes, path) => {
    for (const n of nodes || []) {
      if (n.type === 'dir') {
        walk(n.children, path ? `${path}/${n.name}` : n.name)
      } else if (!keep(n)) {
        continue
      } else if (!path) {
        rootFiles.push(n)
      } else {
        let g = groups.find(x => x.key === path)
        if (!g) { g = { key: path, name: path, files: [] }; groups.push(g) }
        g.files.push(n)
      }
    }
  }
  walk(projTree.value, '')
  const result = []
  if (rootFiles.length) result.push({ key: '__root__', name: '根目录', files: rootFiles })
  return result.concat(groups)
})

function toggleGroup(g) {
  collapsedGroups.value[g.key] = !collapsedGroups.value[g.key]
}

// ===== 项目图纸模式（函数） =====

async function loadMyProjects() {
  try {
    const { data } = await projectsApi.mine()
    myProjects.value = data
    if (data.length && !activeProjectId.value) {
      activeProjectId.value = data[0].id
    }
  } catch { /* 静默 */ }
}

function onSourceModeChange() {
  if (sourceMode.value === 'project') {
    loadMyProjects().then(() => { if (activeProjectId.value) loadProjDrawings() })
  }
  loadHistory()
}

function onProjectChange() {
  selectedDrawingIds.value = []
  projSessionId.value = 0
  loadProjDrawings()
}

async function loadProjDrawings() {
  if (!activeProjectId.value) return
  try {
    const [t, s] = await Promise.all([
      projectsApi.drawingsTree(activeProjectId.value),
      projectsApi.sets(activeProjectId.value),
    ])
    projTree.value = t.data
    projSets.value = s.data
  } catch { /* 静默 */ }
}

// 应用选中的项目图纸：1 张走单图模式，多张建临时图纸集
async function applyProjectDrawings(withSummary) {
  if (!selectedDrawingIds.value.length) return
  projApplying.value = true
  try {
    messages.value = []
    projSessionId.value = 0
    if (selectedDrawingIds.value.length === 1) {
      const did = selectedDrawingIds.value[0]
      const { data: info } = await projectsApi.drawingInfo(activeProjectId.value, did)
      fileId.value = info.file_id
      setId.value = ''
      sheets.value = []
      drawingInfo.value = info
      loadPreview(info.file_id)
    } else {
      const { data } = await drawingApi.projectSet({
        project_id: activeProjectId.value,
        drawing_ids: selectedDrawingIds.value,
      })
      setId.value = data.set_id
      sheets.value = data.sheets
      drawingInfo.value = null
      selectSheet(data.sheets[0].file_id)
    }
    ElMessage.success('图纸已就绪（预处理秒开）')
    if (withSummary) autoSummarize()  // 概述后台错峰执行，不阻塞选图流程
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    projApplying.value = false
  }
}

// 点击图纸集：整组选中并开始问答
function applySet(s) {
  selectedDrawingIds.value = [...s.drawing_ids]
  applyProjectDrawings(true)
}

// 右侧Tab
const rightTab = ref('chat')

// 对话
const messages = ref([])
const question = ref('')
const chatLoading = ref(false)
const summarizing = ref(false)  // 图纸概述后台生成中（错峰，不占用 chatLoading）
const chatContainer = ref(null)

// 材料表
const materials = ref([])
const materialsLoading = ref(false)

// 交底
const briefingProjectName = ref('')
const briefingExtraInfo = ref('')
const briefingContent = ref('')
const briefingLoading = ref(false)

// 历史会话
const historySessions = ref([])

// 图纸预览（渲染 PNG，blob 带 token 取回；PDF 多页逐页探测）
const previewUrls = ref([])

// 预览↕问答 可拖拽比例（%），双击分隔条复位
const previewRatio = ref(55)
let splitCtx = null

function _evY(e) {
  // 兼容鼠标与触摸事件取 Y 坐标
  return e.clientY ?? e.touches?.[0]?.clientY ?? 0
}

function startSplit(e) {
  const col = e.target.closest('.split-divider').parentElement
  splitCtx = { colH: col.getBoundingClientRect().height, startY: _evY(e), startRatio: previewRatio.value }
  document.body.style.userSelect = 'none'
  window.addEventListener('mousemove', onSplitMove)
  window.addEventListener('mouseup', endSplit, { once: true })
  window.addEventListener('touchmove', onSplitMove)
  window.addEventListener('touchend', endSplit, { once: true })
}

function onSplitMove(e) {
  if (!splitCtx) return
  const deltaPct = ((_evY(e) - splitCtx.startY) / splitCtx.colH) * 100
  previewRatio.value = Math.min(85, Math.max(15, splitCtx.startRatio + deltaPct))
}

function endSplit() {
  splitCtx = null
  document.body.style.userSelect = ''
  window.removeEventListener('mousemove', onSplitMove)
  window.removeEventListener('touchmove', onSplitMove)
}

// 历史会话记录覆盖层（钟表按钮呼出）
const historyVisible = ref(false)

// 预览缩放拖动 + 图幅/页切换
const scale = ref(1)
const pan = ref({ x: 0, y: 0 })
const isDragging = ref(false)
const pageIdx = ref(0)
const pageTotal = ref(1)   // 预览总页数（/pages 接口）：_hi/总览 + 全部图框切片
const currentPreviewFid = ref('')
let loadingPages = new Set()
const pzRef = ref(null)
let dragStart = null

const sheetIdx = computed(() => sheets.value.findIndex(s => s.file_id === activeSheetId.value))

// 预览格式切换：PNG（默认）/ DXF（dxf-viewer WebGL 矢量）
// SVG 已移除（2026-10-04）：matplotlib 出图细线糊成等粗，观感差，且与 DXF 矢量重复
const previewMode = ref('png')
const displaySrc = computed(() => previewUrls.value[pageIdx.value])

// ==================== DXF 矢量预览（dxf-viewer，浏览器 WebGL 渲染） ====================
// DXF 源文件由 /drawing/{fid}/dxf 下发（blob 直喂，自带鉴权）；文字用 Noto Sans SC
// （OFL 协议，public/fonts/）。dxf-viewer 自带平移/缩放/触控控件，无需自绘 pz 逻辑。
const dxfUrl = ref('')
const dxfHostRef = ref(null)
const dxfLoading = ref(false)
let dxfViewer = null
let dxfLoadSeq = 0

function destroyDxfViewer() {
  dxfLoadSeq++  // 递增序列号，取消在途的 Load
  dxfLoading.value = false
  if (dxfViewer) {
    try { dxfViewer.Destroy() } catch { /* 已销毁则忽略 */ }
    dxfViewer = null
  }
}

async function mountDxfViewer() {
  destroyDxfViewer()
  const seq = dxfLoadSeq
  const url = dxfUrl.value
  await nextTick()  // 等 dxf-host 渲染进 DOM（构造时要读容器尺寸）
  if (!url || seq !== dxfLoadSeq || previewMode.value !== 'dxf' || !dxfHostRef.value) return
  dxfLoading.value = true
  try {
    const { DxfViewer } = await import('dxf-viewer')
    if (seq !== dxfLoadSeq || previewMode.value !== 'dxf' || !dxfHostRef.value) return
    const viewer = new DxfViewer(dxfHostRef.value, { autoResize: true })
    viewer.SetClearColor('#ffffff')  // 打印风格白底；黑白反转默认开，白色线自动转黑
    dxfViewer = viewer
    window.__dxfViewer = viewer  // 调试钩子（生产也保留：远程诊断相机/白屏用，只读）
    await viewer.Load({
      url,
      fonts: ['/fonts/NotoSansSC-VF.ttf'],
      workerFactory: () => new Worker(
        new URL('../workers/dxfWorker.js', import.meta.url), { type: 'module' }),
    })
    if (seq === dxfLoadSeq) dxfLoading.value = false
  } catch (e) {
    console.error('[DXF 矢量] 加载失败：', e)
    if (seq === dxfLoadSeq && previewMode.value === 'dxf') {
      dxfLoading.value = false
      ElMessage.warning('DXF 矢量渲染失败，已回退 PNG 预览')
      previewMode.value = 'png'
    }
  }
}

watch(previewMode, (m) => {
  if (m === 'dxf') mountDxfViewer()
  else destroyDxfViewer()
})

onBeforeUnmount(destroyDxfViewer)

function switchSheet(delta) {
  const i = sheetIdx.value + delta
  if (i >= 0 && i < sheets.value.length) selectSheet(sheets.value[i].file_id)
}

function resetZoom() {
  scale.value = 1
  pan.value = { x: 0, y: 0 }
}

function onZoom(e) {
  // 以光标位置为锚点缩放（缩放前后光标下的图面点不动）
  const rect = pzRef.value.getBoundingClientRect()
  const cx = e.clientX - rect.left - rect.width / 2
  const cy = e.clientY - rect.top - rect.height / 2
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
  const next = Math.min(10, Math.max(0.2, scale.value * factor))  // 上限1000%
  const k = next / scale.value
  pan.value = { x: cx - (cx - pan.value.x) * k, y: cy - (cy - pan.value.y) * k }
  scale.value = next
}

function startDrag(e) {
  if (snipMode.value) {
    // 截图提问模式：记录框选起点（容器坐标）
    const rect = pzRef.value.getBoundingClientRect()
    snipStart = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    snipRect.value = null
    return
  }
  isDragging.value = true
  dragStart = { x: e.clientX - pan.value.x, y: e.clientY - pan.value.y }
}

function onDrag(e) {
  if (snipMode.value) {
    if (!snipStart) return
    const rect = pzRef.value.getBoundingClientRect()
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top
    snipRect.value = {
      x: Math.min(snipStart.x, cx), y: Math.min(snipStart.y, cy),
      w: Math.abs(cx - snipStart.x), h: Math.abs(cy - snipStart.y),
    }
    return
  }
  if (!isDragging.value || !dragStart) return
  pan.value = { x: e.clientX - dragStart.x, y: e.clientY - dragStart.y }
}

function endDrag() {
  if (snipMode.value) {
    if (snipRect.value && snipRect.value.w > 10 && snipRect.value.h > 10) {
      doSnipCrop()
    }
    snipMode.value = false
    snipStart = null
    return
  }
  isDragging.value = false
  dragStart = null
}

// ==================== 触摸手势（手机端：单指拖动、双指捏合缩放） ====================

let touchState = null  // { mode: 'drag'|'pinch'|'snip', ... }

function onTouchStart(e) {
  const rect = pzRef.value.getBoundingClientRect()
  if (e.touches.length === 1) {
    const t = e.touches[0]
    if (snipMode.value) {
      snipStart = { x: t.clientX - rect.left, y: t.clientY - rect.top }
      snipRect.value = null
      touchState = { mode: 'snip' }
    } else {
      isDragging.value = true
      dragStart = { x: t.clientX - pan.value.x, y: t.clientY - pan.value.y }
      touchState = { mode: 'drag' }
    }
  } else if (e.touches.length === 2) {
    // 双指捏合：记录中心点 + 初始距离 + 初始缩放/平移
    const [a, b] = e.touches
    const cx = (a.clientX + b.clientX) / 2 - rect.left - rect.width / 2
    const cy = (a.clientY + b.clientY) / 2 - rect.top - rect.height / 2
    touchState = {
      mode: 'pinch', cx, cy,
      dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
      startScale: scale.value, startPan: { ...pan.value },
    }
    isDragging.value = false
    dragStart = null
  }
}

function onTouchMove(e) {
  if (!touchState) return
  const rect = pzRef.value.getBoundingClientRect()
  if (touchState.mode === 'drag' && e.touches.length === 1) {
    const t = e.touches[0]
    pan.value = { x: t.clientX - dragStart.x, y: t.clientY - dragStart.y }
  } else if (touchState.mode === 'pinch' && e.touches.length === 2) {
    const [a, b] = e.touches
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
    const factor = dist / touchState.dist
    const next = Math.min(10, Math.max(0.2, touchState.startScale * factor))  // 上限1000%，与滚轮一致
    const k = next / touchState.startScale
    pan.value = {
      x: touchState.cx - (touchState.cx - touchState.startPan.x) * k,
      y: touchState.cy - (touchState.cy - touchState.startPan.y) * k,
    }
    scale.value = next
  } else if (touchState.mode === 'snip' && e.touches.length === 1) {
    const t = e.touches[0]
    const cx = t.clientX - rect.left, cy = t.clientY - rect.top
    snipRect.value = {
      x: Math.min(snipStart.x, cx), y: Math.min(snipStart.y, cy),
      w: Math.abs(cx - snipStart.x), h: Math.abs(cy - snipStart.y),
    }
  }
}

function onTouchEnd(e) {
  if (touchState?.mode === 'snip') {
    if (snipRect.value && snipRect.value.w > 10 && snipRect.value.h > 10) doSnipCrop()
    snipMode.value = false
    snipStart = null
  }
  if (e.touches.length < 2) {
    touchState = null
    isDragging.value = false
    dragStart = null
  }
}

// ==================== 截图提问（框选局部 → 裁剪 → 随问题发送） ====================

const snipMode = ref(false)
const snipRect = ref(null)
const snipBlobUrl = ref('')
let snipStart = null

const snipRectStyle = computed(() => snipRect.value
  ? { left: snipRect.value.x + 'px', top: snipRect.value.y + 'px',
      width: snipRect.value.w + 'px', height: snipRect.value.h + 'px' }
  : {})

function _loadImg(url) {
  return new Promise((res, rej) => {
    const i = new Image()
    i.onload = () => res(i)
    i.onerror = rej
    i.src = url
  })
}

async function doSnipCrop() {
  const rect = snipRect.value
  snipRect.value = null
  try {
    // 始终从 PNG 源图裁剪（DXF 矢量模式下截图也取 PNG 位图——canvas 像素可直接裁）
    const img = await _loadImg(previewUrls.value[pageIdx.value])
    const box = pzRef.value.getBoundingClientRect()
    const cw = box.width, ch = box.height
    // object-fit:contain 适配 + 居中 + 缩放平移 → 容器坐标换算图像像素坐标
    const fs = Math.min(cw / img.naturalWidth, ch / img.naturalHeight) * scale.value
    const dispW = img.naturalWidth * fs, dispH = img.naturalHeight * fs
    const tlX = cw / 2 + pan.value.x - dispW / 2
    const tlY = ch / 2 + pan.value.y - dispH / 2
    const x1 = Math.max(rect.x, tlX), y1 = Math.max(rect.y, tlY)
    const x2 = Math.min(rect.x + rect.w, tlX + dispW), y2 = Math.min(rect.y + rect.h, tlY + dispH)
    if (x2 - x1 < 8 || y2 - y1 < 8) { ElMessage.info('框选区域太小'); return }
    const sx = (x1 - tlX) / fs, sy = (y1 - tlY) / fs
    const sw = (x2 - x1) / fs, sh = (y2 - y1) / fs
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(sw)
    canvas.height = Math.round(sh)
    canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh)
    snipBlobUrl.value = canvas.toDataURL('image/png')
    ElMessage.success('已框选，输入问题后发送即可')
  } catch { /* 裁剪失败静默 */ }
}

// ==================== 语音输入（麦克风录音 → MiMo ASR 服务端识别） ====================

const recognizing = ref(false)
const voiceUploading = ref(false)
let wavRecorder = null

async function toggleVoice() {
  if (recognizing.value) {
    // 停止录音 → 上传识别
    recognizing.value = false
    let blob = null
    try { blob = await wavRecorder?.stop() } catch { /* 编码失败静默 */ }
    wavRecorder = null
    if (!blob) { ElMessage.warning('没有录到声音'); return }
    voiceUploading.value = true
    try {
      const { data } = await drawingApi.asr(new File([blob], 'voice.wav', { type: 'audio/wav' }))
      if (data.text) {
        question.value = question.value ? question.value + data.text : data.text
        ElMessage.success('语音已识别')
      } else {
        ElMessage.warning('未识别到语音内容，请靠近麦克风重试')
      }
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '语音识别失败')
    } finally {
      voiceUploading.value = false
    }
    return
  }
  try {
    wavRecorder = new WavRecorder(60)
    wavRecorder.onMaxReached = () => { if (recognizing.value) toggleVoice() } // 60s 自动停止
    await wavRecorder.start()
    recognizing.value = true
    ElMessage.info('录音中…再点一次结束')
  } catch {
    wavRecorder = null
    ElMessage.warning('无法使用麦克风，请检查浏览器权限（需 HTTPS 或 localhost）')
  }
}

function _revokePreviews() {
  previewUrls.value.forEach(u => URL.revokeObjectURL(u))
  previewUrls.value = []
  if (dxfUrl.value) { URL.revokeObjectURL(dxfUrl.value); dxfUrl.value = '' }
}

async function loadPreview(fid) {
  _revokePreviews()
  currentPreviewFid.value = fid
  loadingPages = new Set()
  previewMode.value = 'png'  // 默认 PNG，右上角按钮可切 DXF 矢量
  pageIdx.value = 0
  pageTotal.value = 1
  try {
    const { data } = await drawingApi.image(fid)
    previewUrls.value.push(URL.createObjectURL(data))
    // 静默探测 DXF 源文件（DWG/DXF 上传有，PDF 无 → 404 不显示矢量按钮）
    drawingApi.dxfFile(fid).then(({ data }) => {
      if (data && data.size > 0) dxfUrl.value = URL.createObjectURL(data)
    }).catch(() => {})
    // 多页（PDF 多页 / 多图框切片）：先取总页数，只预载前 3 页，其余翻页时懒加载
    // （切片图可能几十页，全量预载会把浏览器内存打爆）
    try {
      const { data: p } = await drawingApi.pages(fid)
      pageTotal.value = Math.max(1, p.count || 1)
    } catch { pageTotal.value = 3 }  // 旧后端无 /pages 接口时退回原来的 3 页探测
    await ensurePagesLoaded(Math.min(pageTotal.value, 3))
  } catch {
    previewUrls.value = []
  }
}

// 懒加载第 2..n 页：已加载的跳过，失败（404）记为末页收缩
async function ensurePagesLoaded(n) {
  for (let i = previewUrls.value.length + 1; i <= n; i++) {
    if (loadingPages.has(i)) continue
    loadingPages.add(i)
    try {
      const resp = await drawingApi.imageN(currentPreviewFid.value, i)
      previewUrls.value.push(URL.createObjectURL(resp.data))
    } catch {
      pageTotal.value = Math.min(pageTotal.value, previewUrls.value.length)
      loadingPages.delete(i)
      break
    }
    loadingPages.delete(i)
  }
}

// 翻页时提前 2 页预取，连续翻页不卡
watch(pageIdx, (i) => {
  if (!currentPreviewFid.value) return
  ensurePagesLoaded(Math.min(pageTotal.value, i + 3))
})

async function loadUsage() {}  // 用量统计已移至「日志查询」页（仅超管）

// ACI颜色映射（简化版）
const aciColors = [
  '#000000', '#ff0000', '#ffff00', '#00ff00', '#00ffff',
  '#0000ff', '#ff00ff', '#ffffff', '#808080', '#c0c0c0',
]
function layerColor(index) {
  return aciColors[index] || '#808080'
}

function msgStyle(msg) {
  // 窄屏（手动留在 PC 版的手机）收掉 60px 侧留白，避免消息区只剩几行宽
  const narrow = typeof window !== 'undefined' && window.innerWidth <= 768
  const userPad = narrow ? 16 : 60
  const aiPad = narrow ? 16 : 60
  return {
    display: 'flex',
    justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
    marginBottom: '12px',
    paddingLeft: msg.role === 'user' ? userPad : '16px',
    paddingRight: msg.role === 'user' ? '16px' : aiPad,
  }
}

// 上传区全量罗列：新文件追加进列表（同名同大小去重）
function handleFileChange(file) {
  const dup = fileList.value.some(f => f.name === file.name && f.size === file.size)
  if (dup) { ElMessage.info(`「${file.name}」已在列表中`); return }
  fileList.value.push({
    uid: file.uid, name: file.name, size: file.size,
    raw: file.raw, uploaded: false, file_id: '',
  })
}

// 单文件删除：未解析的仅移出列表；已解析的联动从图纸集移除
async function handleFileRemove(file) {
  const idx = fileList.value.findIndex(f => f.uid === file.uid)
  if (idx < 0) return
  const entry = fileList.value[idx]
  fileList.value.splice(idx, 1)
  if (entry.uploaded && entry.file_id && setId.value) {
    try {
      const { data } = await drawingApi.removeSheet(setId.value, entry.file_id)
      sheets.value = data.sheets || []
      if (activeSheetId.value === entry.file_id) {
        activeSheetId.value = ''
        if (sheets.value.length) selectSheet(sheets.value[0].file_id)
        else { _revokePreviews() }
      }
    } catch { /* 静默 */ }
  }
}

// 一键清空：上传列表+图纸集+预览+对话全部复位
function doClear() {
  fileList.value = []
  uploadRef.value?.clearFiles()
  sessionId.value = ''
  projSessionId.value = 0
  fileId.value = ''
  setId.value = ''
  sheets.value = []
  activeSheetId.value = ''
  drawingInfo.value = null
  messages.value = []
  materials.value = []
  briefingContent.value = ''
  _revokePreviews()
  ElMessage.success('已清空')
}

// 新建会话
function newSession() {
  sessionId.value = ''
  projSessionId.value = 0
  fileId.value = ''
  setId.value = ''
  sheets.value = []
  activeSheetId.value = ''
  drawingInfo.value = null
  messages.value = []
  materials.value = []
  briefingContent.value = ''
  fileList.value = []
  uploadRef.value?.clearFiles()
  _revokePreviews()
}

// 图纸集：点击图幅单独预览
function selectSheet(fid) {
  activeSheetId.value = fid
  fileId.value = fid  // 兼容单图接口（取图/预览）
  pageIdx.value = 0
  resetZoom()
  loadPreview(fid)
}

async function uploadFile() {
  const pending = fileList.value.filter(f => !f.uploaded)
  if (!pending.length) { ElMessage.warning('没有待解析的新文件'); return }
  uploading.value = true
  try {
    // 并行上传（全部新增文件同时解析，比串行快 N 倍）
    const results = await Promise.allSettled(pending.map(f => drawingApi.upload(f.raw)))
    const fileIds = []
    const failed = []
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') {
        pending[i].uploaded = true
        pending[i].file_id = r.value.data.file_id
        fileIds.push(r.value.data.file_id)
      } else {
        const detail = r.reason?.response?.data?.detail || r.reason?.message || '未知原因'
        pending[i].failed = true
        failed.push({ name: pending[i].name, detail })
        console.error('文件解析失败:', pending[i].name, detail)
      }
    })
    if (failed.length) {
      const first = failed[0]
      const summary = failed.length === 1
        ? `「${first.name}」解析失败：${first.detail}`
        : `「${first.name}」等 ${failed.length} 个文件解析失败，首个原因：${first.detail}`
      ElMessage.error({ message: summary, duration: 8000 })
    }
    if (fileIds.length) {
      const { data: setData } = await drawingApi.createSet({
        file_ids: fileIds,
        set_id: setId.value || '',
      })
      setId.value = setData.set_id
      sheets.value = setData.sheets
      drawingInfo.value = null  // 图纸集模式用面板代替概况
      messages.value = []
      ElMessage.success(`图纸集已就绪（${sheets.value.length} 张）`)
      // 预览第一张（首次上传）或保持当前选中
      selectSheet(activeSheetId.value || sheets.value[0].file_id)
      // 先释放上传按钮（自动概述是慢速 LLM 调用，不阻塞继续追加）
      uploading.value = false

      // 自动生成图纸集概述：后台错峰执行，用户可立即提问（一期优化#6）
      await nextTick()
      autoSummarize()
    }
  } catch (e) {
    ElMessage.error('上传失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    uploading.value = false
  }
}

// 图纸概述：后台错峰执行（一期优化#6）——不占用 chatLoading，概述生成期间
// 用户可立即提问；结果回填占位气泡，不打乱对话顺序
async function autoSummarize() {
  if (summarizing.value) return  // 防重复触发（切换图纸/上传并发调用）
  summarizing.value = true
  const placeholder = { role: 'assistant', content: '⏳ 图纸概述生成中…', pending: true }
  messages.value.push(placeholder)
  const summaryQuestion = sheets.value.length > 1
    ? '请综观这套图纸，简要概括：1）这是哪个项目哪个分部的图纸（什么类型的构筑物）；2）套内各图幅分别表达什么；3）各图幅之间的关系（如总图与详图、平面与剖面、设计说明与结构图的对应、图号引用关系），便于后续跨图纸推理；4）有哪些关键的设计参数和标注。提示：各图幅的文件名通常就是图名，图中右下角图框（标题栏）含项目名称、专业、图名、图号、版本等，请以这些信息为主要依据。用简洁的语言总结。'
    : '请根据这张图纸的图层、实体类型和文字标注，简要概括这张图纸的大致内容，包括：1）这可能是什么类型的图纸；2）图中包含哪些主要元素；3）有哪些重要标注信息。提示：文件名通常就是图名，图中右下角图框（标题栏）含项目名称、专业、图名、图号、版本等，请以这些信息为主要依据。用简洁的语言总结。'
  try {
    const { data } = await drawingApi.chat(aiPayload({ question: summaryQuestion }))
    if (data.session_id) projSessionId.value = data.session_id  // 概述即入项目会话
    const ans = {
      role: 'assistant',
      content: data.answer + '\n\n图纸读取完成！关于这套图纸你有什么想问的吗？可以直接向我提问。',
      referenced: data.referenced || [],
    }
    const i = messages.value.indexOf(placeholder)  // 占位回填；会话被切换则追加不覆盖
    if (i >= 0) messages.value[i] = ans
    else messages.value.push(ans)
    // 图纸集总览（含图幅关系）回写存库，后续跨图纸提问注入 prompt 辅助关系推理
    if (setId.value && data.answer) {
      drawingApi.saveSetSummary(setId.value, { summary: data.answer }).catch(() => {})
    }
  } catch (e) {
    const i = messages.value.indexOf(placeholder)
    const ans = {
      role: 'assistant',
      content: '图纸已读取完成。你可以问我关于这套图纸的任何问题。',
    }
    if (i >= 0) messages.value[i] = ans
    else messages.value.push(ans)
  } finally {
    summarizing.value = false
    await nextTick()
    scrollToBottom()
    // 保存会话
    saveCurrentSession()
  }
}

// AI 请求载荷：图纸集优先，单图兜底；项目模式附带 project_id/session_id（脱敏+5天会话）
function aiPayload(extra) {
  const base = setId.value ? { set_id: setId.value } : { file_id: fileId.value }
  if (sourceMode.value === 'project' && activeProjectId.value) {
    base.project_id = activeProjectId.value
    base.session_id = projSessionId.value || 0
    base.drawing_ids = selectedDrawingIds.value
  }
  return { ...base, ...extra }
}

async function sendQuestion() {
  if (!question.value.trim() || !hasContext.value) return

  messages.value.push({ role: 'user', content: question.value })
  const q = question.value
  question.value = ''

  await nextTick()
  scrollToBottom()

  chatLoading.value = true
  try {
    const payload = aiPayload({ question: q, snip_image: snipBlobUrl.value || '' })
    const { data } = await drawingApi.chat(payload)
    messages.value.push({ role: 'assistant', content: data.answer, referenced: data.referenced || [] })
    if (data.session_id) projSessionId.value = data.session_id  // 项目会话（服务端保留5天）
    snipBlobUrl.value = ''  // 截图随本次问题消费，不残留
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '抱歉，回答失败: ' + chatErrMsg(e) })
  } finally {
    chatLoading.value = false
    await nextTick()
    scrollToBottom()
    // 保存会话
    saveCurrentSession()
  }
}

function scrollToBottom() {
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

// 保存当前会话（项目模式会话由服务端在问答时自动落库，这里只刷新列表）
async function saveCurrentSession() {
  if (sourceMode.value === 'project') { loadHistory(); return }
  if (!setId.value && !drawingInfo.value) return
  try {
    const { data } = await drawingApi.saveSession({
      session_id: sessionId.value,
      file_id: fileId.value,
      set_id: setId.value,
      filename: drawingInfo.value?.filename || sheets.value[0]?.filename || '',
      layer_count: drawingInfo.value?.layer_count || 0,
      total_entities: drawingInfo.value?.total_entities || sheets.value.length,
      entity_counts: drawingInfo.value?.entity_counts || {},
      layers: drawingInfo.value?.layers || [],
      text_annotations: drawingInfo.value?.text_annotations || [],
      description: drawingInfo.value?.description || '',
      messages: messages.value,
    })
    if (data.session_id) {
      sessionId.value = data.session_id
    }
    // 刷新历史列表
    loadHistory()
  } catch { /* 静默 */ }
}

// 加载历史会话列表（项目模式：当前项目下我 5 天内的会话）
async function loadHistory() {
  try {
    if (sourceMode.value === 'project') {
      if (!activeProjectId.value) { historySessions.value = []; return }
      const { data } = await projectsApi.sessions(activeProjectId.value)
      historySessions.value = data
    } else {
      const { data } = await drawingApi.listSessions()
      historySessions.value = data
    }
  } catch { /* 静默 */ }
}

// 加载单个会话
async function loadSession(row) {
  // 项目会话：恢复所选图纸 + 对话上下文（服务端返回已还原真实名称）
  if (sourceMode.value === 'project') {
    try {
      const { data } = await projectsApi.getSession(activeProjectId.value, row.id)
      projSessionId.value = data.id
      selectedDrawingIds.value = data.drawing_ids || []
      await applyProjectDrawings(false)  // 恢复图纸上下文，不重复自动概述
      projSessionId.value = data.id      // applyProjectDrawings 会清零，恢复回写
      messages.value = data.messages || []
      materials.value = []
      briefingContent.value = ''
      ElMessage.success(`已恢复会话「${data.title}」（保留至 ${data.expires_at}）`)
      await nextTick()
      scrollToBottom()
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || '加载会话失败')
    }
    return
  }
  try {
    const { data } = await drawingApi.getSession(row.session_id)
    sessionId.value = data.session_id
    setId.value = data.set_id || ''
    if (data.set_id) {
      // 图纸集会话：恢复面板
      try {
        const { data: setData } = await drawingApi.getSet(data.set_id)
        sheets.value = setData.sheets || []
      } catch { sheets.value = [] }
      drawingInfo.value = null
      if (sheets.value.length) selectSheet(sheets.value[0].file_id)
    } else {
      sheets.value = []
      fileId.value = data.file_id
      drawingInfo.value = {
        filename: data.filename,
        layer_count: data.layer_count,
        total_entities: data.total_entities,
        entity_counts: data.entity_counts || {},
        layers: data.layers || [],
        text_annotations: data.text_annotations || [],
        description: data.description || '',
      }
      loadPreview(data.file_id)
    }
    messages.value = data.messages || []
    materials.value = []
    briefingContent.value = ''
    ElMessage.success('已加载会话: ' + data.filename)
    await nextTick()
    scrollToBottom()
  } catch (e) {
    ElMessage.error('加载会话失败')
  }
}

// 删除会话
async function deleteSession(sid) {
  try {
    if (sourceMode.value === 'project') {
      await projectsApi.removeSession(activeProjectId.value, sid)
      if (projSessionId.value === sid) projSessionId.value = 0
    } else {
      await drawingApi.deleteSession(sid)
      if (sessionId.value === sid) {
        newSession()
      }
    }
    ElMessage.success('删除成功')
    loadHistory()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// 材料表提取
async function extractMaterials() {
  if (!hasContext.value) { ElMessage.warning('请先上传图纸'); return }
  materialsLoading.value = true
  try {
    const { data } = await drawingApi.materials(aiPayload({}))
    materials.value = data.materials || []
    loadUsage()
    ElMessage.success(`提取完成，共 ${materials.value.length} 项材料`)
  } catch (e) {
    ElMessage.error('提取失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    materialsLoading.value = false
  }
}

function exportMaterials() {
  if (materials.value.length === 0) { ElMessage.warning('暂无材料数据'); return }
  const header = '序号,材料名称,规格型号,单位,来源图层,备注\n'
  const rows = materials.value.map((m, i) =>
    `${i + 1},"${m.name || ''}","${m.spec || ''}","${m.unit || ''}","${m.layer || ''}","${m.note || ''}"`
  ).join('\n')
  const bom = '﻿'
  const blob = new Blob([bom + header + rows], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `材料表_${drawingInfo.value?.filename || 'drawing'}.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('材料表已导出')
}

// 快速交底
async function generateBriefing() {
  if (!hasContext.value) { ElMessage.warning('请先上传图纸'); return }
  briefingLoading.value = true
  briefingContent.value = ''
  try {
    const { data } = await drawingApi.briefing(aiPayload({
      project_name: briefingProjectName.value,
      extra_info: briefingExtraInfo.value,
    }))
    briefingContent.value = data.briefing
    loadUsage()
    ElMessage.success('交底文件生成成功')
  } catch (e) {
    ElMessage.error('生成失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    briefingLoading.value = false
  }
}

function exportBriefing() {
  if (!briefingContent.value) { ElMessage.warning('暂无交底内容'); return }
  const title = `图纸交底文件\n项目：${briefingProjectName.value || '未指定'}\n图纸：${drawingInfo.value?.filename || ''}\n生成时间：${new Date().toLocaleString()}\n${'='.repeat(50)}\n\n`
  const bom = '﻿'
  const blob = new Blob([bom + title + briefingContent.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `图纸交底_${briefingProjectName.value || drawingInfo.value?.filename || 'briefing'}.txt`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('交底文件已导出')
}

onMounted(() => {
  loadHistory()
  loadMyProjects()
  setTimeout(() => tutorialRef.value?.show(), 500)
})
</script>

<style scoped>
/* 页头/留白统一走 App.vue 全局规范，页面内不重复定义 */
.drawing-layout {
  display: flex;
  gap: 16px;
  height: calc(100vh - 130px);
  height: calc(100dvh - 130px);   /* 移动浏览器工具栏收缩时不裁切底部 */
}
.drawing-left-card {
  width: 380px;
  overflow-y: auto;
  flex-shrink: 0;
}

/* ===== 移动端适配（<768px 手机竖屏）：现场看图优先 ===== */
.mobile-toggle { display: none; }   /* 桌面隐藏展开按钮 */

@media (max-width: 768px) {
  .mobile-toggle { display: inline-flex; }
  .drawing-page { display: flex; flex-direction: column; height: 100%; }
  .drawing-page .page-header { flex-shrink: 0; }
  .drawing-layout {
    flex-direction: column;         /* 左右分栏 → 上下堆叠 */
    flex: 1;
    min-height: 0;
    height: auto;                   /* 用 flex 填满剩余空间，不再硬算高度 */
    gap: 8px;
  }
  .drawing-right-col {
    order: 1;                       /* 预览+问答在上，占满屏 */
    flex: 1;
    min-height: 0;
  }
  .drawing-left-card {
    order: 2;                       /* 上传/图纸集收到底部 */
    width: 100%;
    flex-shrink: 0;
    overflow: visible;
  }
  /* 左卡内容默认收起（只留头部），点「展开」显示，避免挤没问答区 */
  .drawing-left-card :deep(.el-card__body) { display: none; }
  .drawing-left-card.open :deep(.el-card__body) {
    display: block;
    max-height: 45vh;
    overflow-y: auto;
  }
  .page-header h2 { font-size: 15px; line-height: 32px; }   /* 水平对齐全局留白，不再单独加 padding */
  .hint-desktop { display: none; }   /* 手机切手势文案 */
  .hint-mobile { display: inline; }
  /* 手机流量本应走 /m，此块仅为「留在 PC 版」的兜底：消息字号显式 14px、行距可控 */
  .chat-messages { font-size: 14px; }
  .chat-bubble { font-size: 14px; max-width: 92%; line-height: 1.55; }
}
.history-card {
  flex-shrink: 0;
}
.history-card :deep(.el-card__body) {
  padding: 0 16px 16px;
}
.history-card :deep(.el-collapse-item__header) {
  font-weight: 500;
}
.preview-card {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.split-divider {
  height: 10px;
  margin: -3px 0;
  cursor: row-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.split-grip {
  width: 56px;
  height: 4px;
  border-radius: 2px;
  background: #dcdfe6;
  transition: background 0.2s;
}
.split-divider:hover .split-grip,
.split-divider:active .split-grip {
  background: #409eff;
}
.preview-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 8px;
}
.preview-body {
  height: 100%;
}
.pz-container {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  cursor: grab;
  background: #fff;
  border: 1px solid #e6e6e6;
  border-radius: 4px;
}
.pz-container.dragging { cursor: grabbing; }
/* DXF 矢量预览容器（dxf-viewer 会把 canvas 追加进来并接管交互） */
.dxf-host {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  cursor: grab;
  background: #fff;
  border: 1px solid #e6e6e6;
  border-radius: 4px;
}
.dxf-host .pz-hint { z-index: 5; }
.dxf-loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 6;
  font-size: 13px;
  color: #909399;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e6e6e6;
  border-radius: 6px;
  padding: 8px 16px;
  pointer-events: none;
}
.snip-rect {
  position: absolute;
  border: 2px dashed #f56c6c;
  background: rgba(245, 108, 108, 0.12);
  pointer-events: none;
  z-index: 5;
}
.pz-container.snipping { cursor: crosshair; }
.snip-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #606266;
}
.snip-chip img {
  height: 42px;
  border: 1px solid #e6e6e6;
  border-radius: 4px;
}
.voice-btn.recording {
  animation: voice-pulse 1s infinite;
}
@keyframes voice-pulse {
  50% { opacity: 0.45; }
}
.pz-image {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100%;
  height: 100%;
  object-fit: contain;  /* scale(1)=适配容器，缩放以此为基础 */
  user-select: none;
  /* 勿加 will-change: transform——会把 <img src=*.svg> 钉成纹理层按布局分辨率
     预栅格化，滚轮放大后 GPU 拉伸发糊（实测 605% 拉普拉斯方差 1697 vs
     去掉后 5663）。transform 缩放本身走合成，去掉不损失拖动性能 */
}
.pz-pager {
  position: absolute;
  bottom: 10px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #e6e6e6;
  border-radius: 16px;
  padding: 2px 10px;
  font-size: 12px;
  color: #606266;
}
.pz-hint {
  position: absolute;
  top: 8px;
  right: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #c0c4cc;
  background: rgba(255, 255, 255, 0.85);
  padding: 2px 8px;
  border-radius: 12px;
  pointer-events: auto;
}
.hint-mobile { display: none; }   /* 桌面隐藏，手机显示 */
.reset-btn {
  border: none;
  background: #ecf5ff;
  color: #409eff;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  cursor: pointer;
}
.reset-btn:active { background: #d9ecff; }
.clock-row {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed #e6e6e6;
  display: flex;
  align-items: center;
  gap: 10px;
}
.clock-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 2px solid #409eff;
  background: #fff;
  color: #409eff;
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}
.clock-btn:hover, .clock-btn.active {
  background: #409eff;
  color: #fff;
}
.clock-label {
  font-size: 12px;
  color: #909399;
}
.history-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  background: #fff;
  border: 1px solid #e6e6e6;
  border-radius: 4px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  padding: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.history-overlay-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.preview-empty {
  height: 100%;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #909399;
}
.dg-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 4px;
  margin-top: 4px;
  cursor: pointer;
  border-bottom: 1px solid #f2f3f5;
  user-select: none;
}
.sheet-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.sheet-item:hover { background: #f5f7fa; }
.sheet-item.active { background: #ecf5ff; }
.sheet-name {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  max-width: 80%;
}
.chat-bubble.user {
  background: #409eff;
  color: #fff;
}
.chat-bubble.user div:first-child { color: rgba(255,255,255,0.7); }
.chat-bubble.assistant {
  background: #f5f7fa;
  color: #333;
}
.drawing-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: hidden;
}
.drawing-tabs :deep(.el-tabs__content) > .el-tab-pane {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
  min-height: 0;
}
.chat-input-area {
  border-top: 1px solid #e6e6e6;
  padding-top: 12px;
  margin-top: 8px;
}
.chat-input-wrapper {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.chat-textarea {
  flex: 1;
}
.chat-textarea :deep(.el-textarea__inner) {
  padding-right: 48px;
  border-radius: 8px;
}
.chat-send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
}
.chat-send-btn .el-icon {
  font-size: 16px;
  transform: rotate(-45deg);
}
.chat-hint {
  display: block;
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 4px;
}
</style>

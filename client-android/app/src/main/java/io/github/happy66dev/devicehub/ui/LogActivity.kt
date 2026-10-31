package io.github.happy66dev.devicehub.ui

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import io.github.happy66dev.devicehub.core.AgentLog

/**
 * 运行日志页：把服务写进 [AgentLog] 的内容显示出来。
 *
 * 为什么单独一页：主界面已经够长，日志还会一直滚，
 * 分开放才不会把配置区顶到屏幕外喵。
 * 同样不依赖 AndroidX，界面全部用代码创建喵。
 */
class LogActivity : Activity() {

    // 日志正文控件喵
    private lateinit var logView: TextView

    // 日志行数提示喵
    private lateinit var countView: TextView

    // 日志滚动容器，用于自动滚到底部喵
    private lateinit var scrollView: ScrollView

    // 主线程定时刷新用喵
    private val handler = Handler(Looper.getMainLooper())

    // 定时刷新任务喵
    private val refreshTask = object : Runnable {
        override fun run() {
            // 刷新内容喵
            renderLog()
            // 两秒后再刷一次，跟着服务的新日志走喵
            handler.postDelayed(this, REFRESH_INTERVAL_MS)
        }
    }

    /** 界面创建入口喵。 */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 标题喵
        title = "运行日志"
        // 设置界面喵
        setContentView(buildContentView())
        // 首次渲染喵
        renderLog()
    }

    /** 页面可见时开始定时刷新喵。 */
    override fun onResume() {
        super.onResume()
        handler.postDelayed(refreshTask, REFRESH_INTERVAL_MS)
    }

    /** 页面不可见时停掉定时任务，省电喵。 */
    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(refreshTask)
    }

    /** 构造界面：顶部按钮行 + 下方可滚动日志喵。 */
    private fun buildContentView(): LinearLayout {
        // 外层纵向布局喵
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }
        // 行数提示喵
        countView = TextView(this).apply {
            textSize = 13f
            setPadding(0, 0, 0, dp(8))
        }
        // 标题：主题没有 ActionBar，自己画一个喵
        container.addView(TextView(this).apply {
            text = "运行日志"
            textSize = 20f
            setPadding(0, 0, 0, dp(8))
        })
        container.addView(countView)
        // 按钮行喵
        val buttonRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
        }
        // 刷新按钮喵
        buttonRow.addView(actionButton("刷新") { renderLog() })
        // 复制按钮喵
        buttonRow.addView(actionButton("复制") { copyLog() })
        // 清空按钮喵
        buttonRow.addView(actionButton("清空") { clearLog() })
        container.addView(buttonRow)
        // 日志正文喵
        logView = TextView(this).apply {
            textSize = 11f
            // 等宽字体，时间戳才对得齐喵
            typeface = android.graphics.Typeface.MONOSPACE
            setTextIsSelectable(true)
        }
        // 滚动容器喵
        scrollView = ScrollView(this).apply {
            addView(logView)
        }
        // 占满剩余高度喵
        container.addView(
            scrollView,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )
        return container
    }

    /** 添加一个等宽按钮喵。 */
    private fun actionButton(label: String, onClick: () -> Unit): Button {
        // 创建按钮喵
        val button = Button(this).apply {
            text = label
            setOnClickListener { onClick() }
        }
        // 三个按钮平分一行喵
        val params = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        button.layoutParams = params
        return button
    }

    /** 把日志渲染到界面上喵。 */
    private fun renderLog() {
        // 取快照喵
        val lines = AgentLog.snapshot()
        // 更新行数提示喵
        countView.text = if (lines.isEmpty()) {
            "暂无日志（服务启动后会在这里显示）"
        } else {
            "共 ${lines.size} 行，最多保留 ${AgentLog.MAX_LINES} 行"
        }
        // 喵~防御：没有日志时给一句说明，避免界面一片空白喵
        logView.text = if (lines.isEmpty()) "暂无日志" else lines.joinToString("\n")
        // 滚到最新一行喵
        scrollView.post {
            scrollView.fullScroll(ScrollView.FOCUS_DOWN)
        }
    }

    /** 复制全部日志到剪贴板喵。 */
    private fun copyLog() {
        // 取快照喵
        val text = AgentLog.snapshot().joinToString("\n")
        // 喵~防御：没有内容就不复制，免得覆盖用户剪贴板喵
        if (text.isBlank()) {
            Toast.makeText(this, "还没有日志可复制", Toast.LENGTH_SHORT).show()
            return
        }
        // 写剪贴板喵
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("device-hub 日志", text))
        Toast.makeText(this, "日志已复制", Toast.LENGTH_SHORT).show()
    }

    /** 清空日志喵。 */
    private fun clearLog() {
        // 清空缓冲喵
        AgentLog.clear()
        // 重新渲染喵
        renderLog()
        Toast.makeText(this, "日志已清空", Toast.LENGTH_SHORT).show()
    }

    /** dp 转像素喵。 */
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        // 自动刷新间隔，两秒够跟上上报节奏又不费电喵
        private const val REFRESH_INTERVAL_MS = 2000L
    }
}

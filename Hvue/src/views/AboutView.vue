<script setup>
const flow = [
  '客户在首页选择订单，描述问题；建单响应返回 ticketId 与 ticketToken。',
  'Java 校验状态与归属，调用 Python /internal/agent/ask 获取意图、槽位、引用与草稿。',
  'Java 用规则引擎重新核算可退金额与政策，生成 Draft 与 policyCheck 快照。',
  '坐席在工作台核对对话、工具轨迹、引用和金额，修改草稿并填写复核说明。',
  '坐席确认后，Java 在事务中推进状态，事务外模拟执行，再写结果与审计。'
]

const orders = [
  ['O1001', '待发货', '5800 分', '可退；超过 5000 分需要复核说明'],
  ['O1002', '已发货', '12900 分', '物流查询；退款按退货退款处理'],
  ['O1003', '已签收 30 天', '8800 分', '草稿可生成，发送时被政策拦截'],
  ['O1006', '待发货', '25000 分', '必须复核；政策硬上限校验'],
  ['O1010', '已签收，已全额退款', '5000 分', '可退 0，转人工且不给金额'],
  ['O9999', '不存在', '—', '第一次追问订单号，第二次转人工']
]
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Demo Guide</div>
        <h1 class="title">演示说明</h1>
        <p class="subtitle">
          这是一套可本地跑通的售后辅助处理演示：Java 负责裁决与落库，Python 只做只读建议，
          坐席做最终确认。所有资金动作均为模拟。
        </p>
      </div>
      <RouterLink class="btn" to="/">回到客户入口</RouterLink>
    </div>

    <div class="grid grid--3">
      <section class="panel">
        <div class="panel-head"><h2>Java · 唯一裁决方</h2></div>
        <div class="panel-body about-list">
          <div class="about-item"><span>✓</span><span>身份、状态机、幂等、版本与审计。</span></div>
          <div class="about-item"><span>✓</span><span>政策规则与可退金额的最终计算。</span></div>
          <div class="about-item"><span>✓</span><span>确认、执行、关闭的唯一写入口。</span></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Python · 只读建议</h2></div>
        <div class="panel-body about-list">
          <div class="about-item"><span>✓</span><span>意图识别、槽位抽取、政策检索。</span></div>
          <div class="about-item"><span>✓</span><span>生成回复草稿与引用，不接触数据库。</span></div>
          <div class="about-item"><span>✓</span><span>不接收也不返回 policyCheck。</span></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>坐席 · 最终确认</h2></div>
        <div class="panel-body about-list">
          <div class="about-item"><span>✓</span><span>核对订单、物流、政策与金额。</span></div>
          <div class="about-item"><span>✓</span><span>修改草稿；需要时填写复核说明。</span></div>
          <div class="about-item"><span>✓</span><span>决定发送、转人工、回复或关闭。</span></div>
        </div>
      </section>
    </div>

    <div class="about-grid">
      <section class="panel">
        <div class="panel-head"><h2>推荐演示路径</h2></div>
        <div class="panel-body about-list">
          <div v-for="(step, index) in flow" :key="index" class="about-item">
            <span>{{ index + 1 }}</span><span>{{ step }}</span>
          </div>
          <div class="notice" style="margin-top: 6px">
            咨询中改口“那就帮我退了吧”，会新建一张关联售后单，并在响应里回传
            <code>createdTicket</code>；客户侧不需要理解内部状态。
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>订单夹具</h2>
          <span class="hint">U001 / U002</span>
        </div>
        <div class="panel-body">
          <table class="queue-table">
            <thead>
              <tr><th>订单</th><th>场景</th><th>金额</th><th>预期</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in orders" :key="row[0]">
                <td><span class="queue-link">{{ row[0] }}</span></td>
                <td>{{ row[1] }}</td>
                <td style="white-space: nowrap">{{ row[2] }}</td>
                <td style="font-size: 11.5px; color: var(--muted)">{{ row[3] }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div class="about-grid">
      <section class="panel">
        <div class="panel-head"><h2>边界与已知限制</h2></div>
        <div class="panel-body about-list">
          <div class="about-item"><span>!</span><span>一期不接真实支付/退款，执行模式固定为 SIMULATED。</span></div>
          <div class="about-item"><span>!</span><span>演示身份使用 X-User-Id 白名单；生产必须接 SSO 并关闭演示头。</span></div>
          <div class="about-item"><span>!</span><span>本地默认 H2；MySQL 8 的行为尚未做真机验收。</span></div>
          <div class="about-item"><span>!</span><span>取号是单实例实现；多实例需要数据库原子序列。</span></div>
          <div class="about-item"><span>!</span><span>并发用例目前以请求顺序验证，未做线程级压测。</span></div>
          <div class="about-item"><span>!</span><span>前端不展示 intent/confidence 给客户；坐席视图才可见。</span></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>本地启动</h2></div>
        <div class="panel-body grid">
          <div class="code-block"># Java（JDK 17）
cd java
mvn test
mvn package
java -jar target/aftersale-agent-java-0.1.0-SNAPSHOT.jar

# Python
cd python
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

# 前端
cd Hvue
pnpm install
pnpm dev
# http://localhost:5173</div>
          <p class="hint">
            Java 默认使用 scripted 模式；联调 Python 时加
            <code>--app.agent.mode=http</code>。前端通过 Vite 将 <code>/api</code> 代理到 8080。
          </p>
        </div>
      </section>
    </div>

    <section class="panel" style="margin-top: 18px">
      <div class="panel-head"><h2>验收口径</h2></div>
      <div class="panel-body grid grid--3">
        <div><div class="section-title">Java · M-S</div><p style="margin-top: 5px">19 个 H2 集成测试通过，覆盖 AC01–AC26 的主要路径。</p></div>
        <div><div class="section-title">Python · 单测</div><p style="margin-top: 5px">21 个 pytest 通过，覆盖严格契约、HMAC、工具降级与安全闸。</p></div>
        <div><div class="section-title">前端 · 构建</div><p style="margin-top: 5px">Vite 生产构建通过；交互以服务端错误码为准，不自行放行。</p></div>
      </div>
    </section>
  </div>
</template>

package com.chinayiru.aftersale.agent;

/**
 * Java 调用 Python AI 层的唯一出口。实现必须无副作用、不写库。
 */
public interface AgentClient {

    AgentContract.AskResponse ask(AgentContract.AskRequest request, String internalIdentity);

    String provider();
}

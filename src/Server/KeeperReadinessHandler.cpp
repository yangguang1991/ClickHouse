#include <memory>
#include <Server/KeeperReadinessHandler.h>

#include <Databases/IDatabase.h>
#include <IO/HTTPCommon.h>
#include <Interpreters/Context.h>
#include <Server/HTTP/HTMLForm.h>
#include <Server/HTTPHandlerFactory.h>
#include <Server/HTTPHandlerRequestFilter.h>
#include <Server/IServer.h>
#include <Storages/StorageReplicatedMergeTree.h>
#include "Common/tests/gtest_global_context.h"
#include <Common/typeid_cast.h>
#include "Coordination/KeeperDispatcher.h"
#include <Server/HTTP/WriteBufferFromHTTPServerResponse.h>

#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>


namespace DB
{

void KeeperReadinessHandler::handleRequest(HTTPServerRequest & /*request*/, HTTPServerResponse & response)
{
    try
    {
        // auto keeper_info = keeper_dispatcher->getKeeper4LWInfo();
        auto leader = keeper_dispatcher->isLeader();// && keeper_info.follower_count > 0;
        auto follower = keeper_dispatcher->isFollower() && keeper_dispatcher->hasLeader();
        if (leader || follower)
        {
            *response.send() << "imok";
        }
        else
        {
            response.setStatusAndReason(Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
            *response.send() << "imnotok";
        }
    }
    catch (...)
    {
        tryLogCurrentException("KeeperCloudRequestHandler");
    }
}


HTTPRequestHandlerFactoryPtr createKeeperCloudMainHandlerFactory(
    IServer & server,
    const Poco::Util::AbstractConfiguration & config,
    std::shared_ptr<KeeperDispatcher> keeper_dispatcher,
    const std::string & name)
{
    auto factory = std::make_shared<HTTPRequestHandlerFactoryMain>(name);
    using Factory = HandlingRuleHTTPHandlerFactory<KeeperReadinessHandler>;
    Factory::Creator creator = [&server, keeper_dispatcher]() -> std::unique_ptr<KeeperReadinessHandler>
    {
        return std::make_unique<KeeperReadinessHandler>(server, keeper_dispatcher);
    };

    auto handler = std::make_shared<Factory>(std::move(creator));

    handler->attachNonStrictPath(config.getString("cloud.readiness.endpoint", "/cloud_readiness"));
    handler->allowGetAndHeadRequest();
    factory->addHandler(handler);
    return factory;
}

}

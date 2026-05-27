#include "information-topology.h"

#include "ns3/fatal-error.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <exception>
#include <fstream>
#include <iterator>
#include <limits>
#include <queue>
#include <regex>
#include <sstream>

namespace ns3
{

namespace
{

constexpr double EARTH_RADIUS_KM = 6371.0;
constexpr double FIBER_KM_PER_MS = 200.0;
constexpr double PI = 3.14159265358979323846;

std::string
ReplaceAll(std::string text, const std::string& from, const std::string& to)
{
    std::size_t pos = 0;
    while ((pos = text.find(from, pos)) != std::string::npos)
    {
        text.replace(pos, from.length(), to);
        pos += to.length();
    }
    return text;
}

std::string
UnescapeXml(std::string text)
{
    text = ReplaceAll(text, "&amp;", "&");
    text = ReplaceAll(text, "&lt;", "<");
    text = ReplaceAll(text, "&gt;", ">");
    text = ReplaceAll(text, "&quot;", "\"");
    text = ReplaceAll(text, "&apos;", "'");
    return text;
}

std::map<std::string, std::string>
ParseXmlAttributes(const std::string& tag)
{
    std::map<std::string, std::string> attributes;
    std::regex attrRegex("([A-Za-z_:][A-Za-z0-9_:\\.-]*)\\s*=\\s*\"([^\"]*)\"");
    for (auto it = std::sregex_iterator(tag.begin(), tag.end(), attrRegex);
         it != std::sregex_iterator();
         ++it)
    {
        attributes[(*it)[1].str()] = UnescapeXml((*it)[2].str());
    }
    return attributes;
}

bool
TryParseDouble(const std::string& text, double* value)
{
    try
    {
        std::size_t parsed = 0;
        double parsedValue = std::stod(text, &parsed);
        if (parsed == 0)
        {
            return false;
        }
        *value = parsedValue;
        return true;
    }
    catch (const std::exception&)
    {
        return false;
    }
}

std::string
ToLower(std::string text)
{
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {
        return std::tolower(c);
    });
    return text;
}

std::string
Lookup(const std::map<std::string, std::string>& values, const std::string& key)
{
    auto it = values.find(key);
    if (it == values.end())
    {
        return "";
    }
    return it->second;
}

DataRate
ParseDataRate(const std::map<std::string, std::string>& values, DataRate fallback)
{
    double raw = 0.0;
    if (TryParseDouble(Lookup(values, "LinkSpeedRaw"), &raw) && raw > 0.0)
    {
        return DataRate(static_cast<uint64_t>(std::llround(raw)));
    }

    std::string text = Lookup(values, "LinkSpeed");
    std::string units = Lookup(values, "LinkSpeedUnits");
    if (text.empty())
    {
        text = Lookup(values, "LinkLabel");
    }
    if (text.empty())
    {
        text = Lookup(values, "LinkType");
    }
    if (text.empty())
    {
        return fallback;
    }

    std::string normalized = ToLower(text + units);
    normalized = ReplaceAll(normalized, " ", "");

    std::smatch ocMatch;
    std::regex ocRegex(R"(oc-?([0-9]+))");
    if (std::regex_search(normalized, ocMatch, ocRegex))
    {
        double ocLevel = 0.0;
        if (TryParseDouble(ocMatch[1].str(), &ocLevel) && ocLevel > 0.0)
        {
            return DataRate(static_cast<uint64_t>(std::llround(ocLevel * 51840000.0)));
        }
    }

    std::smatch rateMatch;
    std::regex rateRegex(R"(([0-9]+(?:\.[0-9]+)?)([kmgt]?))");
    if (!std::regex_search(normalized, rateMatch, rateRegex))
    {
        return fallback;
    }

    double value = 0.0;
    if (!TryParseDouble(rateMatch[1].str(), &value) || value <= 0.0)
    {
        return fallback;
    }

    std::string unit = rateMatch[2].str();
    double multiplier = 1.0;
    if (unit == "k")
    {
        multiplier = 1e3;
    }
    else if (unit == "m")
    {
        multiplier = 1e6;
    }
    else if (unit == "g")
    {
        multiplier = 1e9;
    }
    else if (unit == "t")
    {
        multiplier = 1e12;
    }
    return DataRate(static_cast<uint64_t>(std::llround(value * multiplier)));
}

double
Radians(double degrees)
{
    return degrees * PI / 180.0;
}

double
DistanceKm(const InformationTopologyNode& a, const InformationTopologyNode& b)
{
    double lat1 = Radians(a.latitude);
    double lat2 = Radians(b.latitude);
    double dLat = Radians(b.latitude - a.latitude);
    double dLon = Radians(b.longitude - a.longitude);
    double sinLat = std::sin(dLat / 2.0);
    double sinLon = std::sin(dLon / 2.0);
    double h = (sinLat * sinLat) + (std::cos(lat1) * std::cos(lat2) * sinLon * sinLon);
    return 2.0 * EARTH_RADIUS_KM * std::asin(std::sqrt(h));
}

std::map<std::string, std::string>
ParseDataBlock(const std::string& block, const std::map<std::string, std::string>& keyNames)
{
    std::map<std::string, std::string> values;
    std::regex dataRegex("<data\\s+key=\"([^\"]+)\"\\s*>([\\s\\S]*?)</data>");
    for (auto it = std::sregex_iterator(block.begin(), block.end(), dataRegex);
         it != std::sregex_iterator();
         ++it)
    {
        std::string key = (*it)[1].str();
        std::string name = key;
        auto nameIt = keyNames.find(key);
        if (nameIt != keyNames.end())
        {
            name = nameIt->second;
        }
        values[name] = UnescapeXml((*it)[2].str());
    }
    return values;
}

std::string
MakeNodeId(uint32_t index)
{
    return "n" + std::to_string(index);
}

} // namespace

InformationTopology::InformationTopology()
{
}

void
InformationTopology::Clear()
{
    m_nodes.clear();
    m_links.clear();
    m_adjacency.clear();
    m_idToIndex.clear();
}

uint32_t
InformationTopology::AddNode(const std::string& id, const std::string& name)
{
    NS_ABORT_MSG_IF(id.empty(), "Topology node id must not be empty");
    NS_ABORT_MSG_IF(HasNode(id), "Duplicate topology node id: " << id);

    InformationTopologyNode node;
    node.id = id;
    node.name = name.empty() ? id : name;
    node.latitude = 0.0;
    node.longitude = 0.0;
    node.hasPosition = false;

    uint32_t index = m_nodes.size();
    m_nodes.push_back(node);
    m_adjacency.emplace_back();
    m_idToIndex[id] = index;
    return index;
}

void
InformationTopology::SetNodePosition(uint32_t index, double latitude, double longitude)
{
    NS_ABORT_MSG_IF(index >= m_nodes.size(), "Topology node index out of range");
    m_nodes[index].latitude = latitude;
    m_nodes[index].longitude = longitude;
    m_nodes[index].hasPosition = true;
}

uint32_t
InformationTopology::AddLink(uint32_t from,
                             uint32_t to,
                             double cost,
                             Time delay,
                             DataRate dataRate,
                             const std::string& label)
{
    NS_ABORT_MSG_IF(from >= m_nodes.size(), "Link source node index out of range");
    NS_ABORT_MSG_IF(to >= m_nodes.size(), "Link target node index out of range");
    NS_ABORT_MSG_IF(from == to, "Self links are not supported");
    NS_ABORT_MSG_IF(cost <= 0.0, "Link cost must be positive");

    InformationTopologyLink link;
    link.from = from;
    link.to = to;
    link.cost = cost;
    link.delay = delay;
    link.dataRate = dataRate;
    link.label = label;

    uint32_t index = m_links.size();
    m_links.push_back(link);
    m_adjacency[from].push_back(index);
    m_adjacency[to].push_back(index);
    return index;
}

uint32_t
InformationTopology::AddLink(const std::string& fromId,
                             const std::string& toId,
                             double cost,
                             Time delay,
                             DataRate dataRate,
                             const std::string& label)
{
    return AddLink(GetNodeIndex(fromId), GetNodeIndex(toId), cost, delay, dataRate, label);
}

uint32_t
InformationTopology::GetNNodes() const
{
    return m_nodes.size();
}

uint32_t
InformationTopology::GetNLinks() const
{
    return m_links.size();
}

const InformationTopologyNode&
InformationTopology::GetNode(uint32_t index) const
{
    NS_ABORT_MSG_IF(index >= m_nodes.size(), "Topology node index out of range");
    return m_nodes[index];
}

const InformationTopologyLink&
InformationTopology::GetLink(uint32_t index) const
{
    NS_ABORT_MSG_IF(index >= m_links.size(), "Topology link index out of range");
    return m_links[index];
}

void
InformationTopology::SetLinkCost(uint32_t index, double cost)
{
    NS_ABORT_MSG_IF(index >= m_links.size(), "Topology link index out of range");
    NS_ABORT_MSG_IF(cost <= 0.0, "Link cost must be positive");
    m_links[index].cost = cost;
}

void
InformationTopology::SetLinkDelay(uint32_t index, Time delay)
{
    NS_ABORT_MSG_IF(index >= m_links.size(), "Topology link index out of range");
    m_links[index].delay = delay;
}

void
InformationTopology::SetLinkDataRate(uint32_t index, DataRate dataRate)
{
    NS_ABORT_MSG_IF(index >= m_links.size(), "Topology link index out of range");
    m_links[index].dataRate = dataRate;
}

bool
InformationTopology::HasNode(const std::string& id) const
{
    return m_idToIndex.find(id) != m_idToIndex.end();
}

uint32_t
InformationTopology::GetNodeIndex(const std::string& id) const
{
    auto it = m_idToIndex.find(id);
    NS_ABORT_MSG_IF(it == m_idToIndex.end(), "Unknown topology node id: " << id);
    return it->second;
}

const std::vector<uint32_t>&
InformationTopology::GetAdjacentLinks(uint32_t node) const
{
    NS_ABORT_MSG_IF(node >= m_adjacency.size(), "Topology node index out of range");
    return m_adjacency[node];
}

uint32_t
InformationTopology::GetOtherNode(uint32_t link, uint32_t node) const
{
    const auto& entry = GetLink(link);
    if (entry.from == node)
    {
        return entry.to;
    }
    NS_ABORT_MSG_IF(entry.to != node, "Node is not an endpoint of the requested link");
    return entry.from;
}

int64_t
InformationTopology::FindLink(uint32_t from, uint32_t to) const
{
    NS_ABORT_MSG_IF(from >= m_nodes.size() || to >= m_nodes.size(), "Topology node index out of range");
    int64_t best = -1;
    double bestCost = std::numeric_limits<double>::infinity();
    for (uint32_t linkIndex : m_adjacency[from])
    {
        const auto& link = m_links[linkIndex];
        uint32_t other = link.from == from ? link.to : link.from;
        if (other == to && link.cost < bestCost)
        {
            best = linkIndex;
            bestCost = link.cost;
        }
    }
    return best;
}

double
InformationTopology::GetPathCost(const std::vector<uint32_t>& nodes) const
{
    if (nodes.size() < 2)
    {
        return 0.0;
    }
    double cost = 0.0;
    for (uint32_t i = 0; i + 1 < nodes.size(); ++i)
    {
        int64_t link = FindLink(nodes[i], nodes[i + 1]);
        NS_ABORT_MSG_IF(link < 0, "Path contains non-adjacent nodes");
        cost += m_links[link].cost;
    }
    return cost;
}

InformationPath
InformationTopology::ShortestPath(
    uint32_t source,
    uint32_t target,
    const std::set<uint32_t>& bannedNodes,
    const std::set<std::pair<uint32_t, uint32_t>>& bannedEdges) const
{
    InformationPath empty;
    empty.cost = std::numeric_limits<double>::infinity();
    if (source >= m_nodes.size() || target >= m_nodes.size() || bannedNodes.count(source))
    {
        return empty;
    }

    std::vector<double> dist(m_nodes.size(), std::numeric_limits<double>::infinity());
    std::vector<uint32_t> previous(m_nodes.size(), std::numeric_limits<uint32_t>::max());
    using QueueEntry = std::pair<double, uint32_t>;
    std::priority_queue<QueueEntry, std::vector<QueueEntry>, std::greater<QueueEntry>> queue;

    dist[source] = 0.0;
    queue.emplace(0.0, source);

    while (!queue.empty())
    {
        auto [currentCost, current] = queue.top();
        queue.pop();
        if (currentCost > dist[current])
        {
            continue;
        }
        if (current == target)
        {
            break;
        }

        for (uint32_t linkIndex : m_adjacency[current])
        {
            uint32_t next = GetOtherNode(linkIndex, current);
            if (bannedNodes.count(next) || bannedEdges.count({current, next}))
            {
                continue;
            }
            double candidate = currentCost + m_links[linkIndex].cost;
            if (candidate + 1e-12 < dist[next])
            {
                dist[next] = candidate;
                previous[next] = current;
                queue.emplace(candidate, next);
            }
        }
    }

    if (!std::isfinite(dist[target]))
    {
        return empty;
    }

    std::vector<uint32_t> path;
    for (uint32_t node = target; node != std::numeric_limits<uint32_t>::max(); node = previous[node])
    {
        path.push_back(node);
        if (node == source)
        {
            break;
        }
    }
    std::reverse(path.begin(), path.end());
    if (path.empty() || path.front() != source)
    {
        return empty;
    }

    InformationPath result;
    result.nodes = path;
    result.cost = dist[target];
    return result;
}

bool
InformationTopology::SamePrefix(const std::vector<uint32_t>& path,
                                const std::vector<uint32_t>& prefix) const
{
    if (path.size() < prefix.size())
    {
        return false;
    }
    return std::equal(prefix.begin(), prefix.end(), path.begin());
}

bool
InformationTopology::ContainsPath(const std::vector<InformationPath>& paths,
                                  const std::vector<uint32_t>& candidate) const
{
    for (const auto& path : paths)
    {
        if (path.nodes == candidate)
        {
            return true;
        }
    }
    return false;
}

std::vector<InformationPath>
InformationTopology::GetKShortestPaths(uint32_t source, uint32_t target, uint32_t k) const
{
    std::vector<InformationPath> result;
    if (k == 0 || source == target)
    {
        return result;
    }

    InformationPath first = ShortestPath(source, target, {}, {});
    if (first.nodes.empty())
    {
        return result;
    }
    result.push_back(first);

    std::vector<InformationPath> candidates;
    for (uint32_t pathIndex = 1; pathIndex < k; ++pathIndex)
    {
        const auto& previousPath = result[pathIndex - 1].nodes;
        for (uint32_t spurIndex = 0; spurIndex + 1 < previousPath.size(); ++spurIndex)
        {
            uint32_t spurNode = previousPath[spurIndex];
            std::vector<uint32_t> rootPath(previousPath.begin(), previousPath.begin() + spurIndex + 1);

            std::set<std::pair<uint32_t, uint32_t>> bannedEdges;
            for (const auto& path : result)
            {
                if (SamePrefix(path.nodes, rootPath) && path.nodes.size() > spurIndex + 1)
                {
                    bannedEdges.insert({path.nodes[spurIndex], path.nodes[spurIndex + 1]});
                }
            }

            std::set<uint32_t> bannedNodes;
            for (uint32_t i = 0; i + 1 < rootPath.size(); ++i)
            {
                bannedNodes.insert(rootPath[i]);
            }

            InformationPath spurPath = ShortestPath(spurNode, target, bannedNodes, bannedEdges);
            if (spurPath.nodes.empty())
            {
                continue;
            }

            std::vector<uint32_t> totalPath = rootPath;
            totalPath.insert(totalPath.end(), spurPath.nodes.begin() + 1, spurPath.nodes.end());
            if (!ContainsPath(result, totalPath) && !ContainsPath(candidates, totalPath))
            {
                InformationPath candidate;
                candidate.nodes = totalPath;
                candidate.cost = GetPathCost(totalPath);
                candidates.push_back(candidate);
            }
        }

        if (candidates.empty())
        {
            break;
        }

        std::sort(candidates.begin(), candidates.end(), [](const auto& left, const auto& right) {
            if (left.cost != right.cost)
            {
                return left.cost < right.cost;
            }
            return left.nodes < right.nodes;
        });
        result.push_back(candidates.front());
        candidates.erase(candidates.begin());
    }

    return result;
}

InformationTopology
InformationTopology::ReadGraphml(const std::string& fileName, Time defaultDelay, DataRate defaultDataRate)
{
    std::ifstream input(fileName);
    NS_ABORT_MSG_IF(!input, "Unable to open GraphML topology file: " << fileName);
    std::string xml((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());

    std::map<std::string, std::string> keyNames;
    std::regex keyRegex(R"(<key\s+([^>]*)/?>)");
    for (auto it = std::sregex_iterator(xml.begin(), xml.end(), keyRegex);
         it != std::sregex_iterator();
         ++it)
    {
        auto attributes = ParseXmlAttributes((*it)[1].str());
        if (!attributes["id"].empty() && !attributes["attr.name"].empty())
        {
            keyNames[attributes["id"]] = attributes["attr.name"];
        }
    }

    InformationTopology topology;
    std::regex nodeRegex(R"(<node\s+([^>]*)>([\s\S]*?)</node>)");
    for (auto it = std::sregex_iterator(xml.begin(), xml.end(), nodeRegex);
         it != std::sregex_iterator();
         ++it)
    {
        auto attributes = ParseXmlAttributes((*it)[1].str());
        std::string id = attributes["id"];
        auto values = ParseDataBlock((*it)[2].str(), keyNames);
        std::string name = Lookup(values, "label");
        uint32_t index = topology.AddNode(id, name.empty() ? id : name);

        double latitude = 0.0;
        double longitude = 0.0;
        if (TryParseDouble(Lookup(values, "Latitude"), &latitude) &&
            TryParseDouble(Lookup(values, "Longitude"), &longitude))
        {
            topology.SetNodePosition(index, latitude, longitude);
        }
    }

    std::regex edgeRegex(R"(<edge\s+([^>]*)>([\s\S]*?)</edge>)");
    for (auto it = std::sregex_iterator(xml.begin(), xml.end(), edgeRegex);
         it != std::sregex_iterator();
         ++it)
    {
        auto attributes = ParseXmlAttributes((*it)[1].str());
        std::string source = attributes["source"];
        std::string target = attributes["target"];
        auto values = ParseDataBlock((*it)[2].str(), keyNames);

        uint32_t from = topology.GetNodeIndex(source);
        uint32_t to = topology.GetNodeIndex(target);
        const auto& fromNode = topology.GetNode(from);
        const auto& toNode = topology.GetNode(to);

        Time delay = defaultDelay;
        double delayMs = 0.0;
        if (TryParseDouble(Lookup(values, "Delay"), &delayMs) ||
            TryParseDouble(Lookup(values, "Latency"), &delayMs))
        {
            delay = Seconds(delayMs / 1000.0);
        }
        else if (fromNode.hasPosition && toNode.hasPosition)
        {
            double geoDelayMs =
                std::max(defaultDelay.ToDouble(Time::MS), DistanceKm(fromNode, toNode) / FIBER_KM_PER_MS);
            delay = Seconds(geoDelayMs / 1000.0);
        }

        std::string label = Lookup(values, "LinkLabel");
        if (label.empty())
        {
            label = Lookup(values, "LinkType");
        }
        DataRate dataRate = ParseDataRate(values, defaultDataRate);
        double cost = std::max(0.001, delay.ToDouble(Time::MS));
        topology.AddLink(from, to, cost, delay, dataRate, label);
    }

    return topology;
}

InformationTopology
InformationTopology::CreateRing(uint32_t nodes, Time delay, DataRate dataRate)
{
    NS_ABORT_MSG_IF(nodes < 2, "Ring topology requires at least two nodes");
    InformationTopology topology;
    for (uint32_t i = 0; i < nodes; ++i)
    {
        topology.AddNode(MakeNodeId(i));
    }
    for (uint32_t i = 0; i + 1 < nodes; ++i)
    {
        topology.AddLink(i, i + 1, 1.0, delay, dataRate, "ring");
    }
    if (nodes > 2)
    {
        topology.AddLink(nodes - 1, 0, 1.0, delay, dataRate, "ring");
    }
    return topology;
}

InformationTopology
InformationTopology::CreateGrid(uint32_t rows, uint32_t columns, Time delay, DataRate dataRate)
{
    NS_ABORT_MSG_IF(rows == 0 || columns == 0, "Grid dimensions must be positive");
    InformationTopology topology;
    for (uint32_t row = 0; row < rows; ++row)
    {
        for (uint32_t column = 0; column < columns; ++column)
        {
            topology.AddNode("r" + std::to_string(row) + "c" + std::to_string(column));
        }
    }

    auto index = [columns](uint32_t row, uint32_t column) {
        return row * columns + column;
    };
    for (uint32_t row = 0; row < rows; ++row)
    {
        for (uint32_t column = 0; column < columns; ++column)
        {
            if (column + 1 < columns)
            {
                topology.AddLink(index(row, column), index(row, column + 1), 1.0, delay, dataRate, "grid");
            }
            if (row + 1 < rows)
            {
                topology.AddLink(index(row, column), index(row + 1, column), 1.0, delay, dataRate, "grid");
            }
        }
    }
    return topology;
}

InformationTopology
InformationTopology::CreateTieredBackbone(uint32_t regions,
                                          uint32_t metrosPerRegion,
                                          uint32_t edgesPerMetro,
                                          Time delay,
                                          DataRate dataRate)
{
    NS_ABORT_MSG_IF(regions < 2, "Tiered backbone requires at least two regions");
    NS_ABORT_MSG_IF(metrosPerRegion == 0 || edgesPerMetro == 0,
                    "Tiered backbone fanout must be positive");

    InformationTopology topology;
    std::vector<uint32_t> hubs;
    for (uint32_t region = 0; region < regions; ++region)
    {
        hubs.push_back(topology.AddNode("region-" + std::to_string(region)));
    }

    for (uint32_t region = 0; region + 1 < regions; ++region)
    {
        topology.AddLink(hubs[region], hubs[region + 1], 1.0, delay, dataRate, "core");
    }
    topology.AddLink(hubs.back(), hubs.front(), 1.0, delay, dataRate, "core");
    if (regions > 3)
    {
        for (uint32_t region = 0; region < regions; ++region)
        {
            uint32_t other = (region + 2) % regions;
            if (region < other)
            {
                topology.AddLink(hubs[region], hubs[other], 1.5, delay, dataRate, "core-chord");
            }
        }
    }

    for (uint32_t region = 0; region < regions; ++region)
    {
        for (uint32_t metro = 0; metro < metrosPerRegion; ++metro)
        {
            uint32_t metroNode = topology.AddNode("region-" + std::to_string(region) + "-metro-" +
                                                  std::to_string(metro));
            topology.AddLink(hubs[region], metroNode, 1.0, delay, dataRate, "metro");
            for (uint32_t edge = 0; edge < edgesPerMetro; ++edge)
            {
                uint32_t edgeNode = topology.AddNode("region-" + std::to_string(region) + "-metro-" +
                                                     std::to_string(metro) + "-edge-" +
                                                     std::to_string(edge));
                topology.AddLink(metroNode, edgeNode, 1.0, delay, dataRate, "edge");
            }
        }
    }

    return topology;
}

} // namespace ns3

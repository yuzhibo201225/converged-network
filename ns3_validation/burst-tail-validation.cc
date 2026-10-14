/*
 * Packet-level validation scenario for heterogeneous burst contention.
 *
 * This file is intentionally self-contained and targets ns-3.47.  Offered
 * load is defined using IPv4 packet bytes (IPv4 header + UDP header + payload)
 * divided by the configured nominal bottleneck bit rate.  Point-to-point link
 * framing adds a small amount of serialization overhead, which is deliberately
 * not hidden by the reported realized offered-load value.
 */

#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("BurstTailValidation");

namespace
{

constexpr uint32_t kWireHeaderMagic = 0x42544c56; // "BTLV"
constexpr uint32_t kIpv4UdpHeaderBytes = 28;
constexpr uint16_t kSinkPort = 9000;
constexpr double kTolerance = 1e-9;

enum class FlowKind : uint8_t
{
    CONTROL = 1,
    SENSOR = 2,
    BULK = 3,
};

struct Emission
{
    double timeSeconds{};
    uint32_t sequence{};
};

struct Reception
{
    double receiveTimeSeconds{};
    double latencySeconds{};
};

class ExperimentHeader : public Header
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::BurstTailExperimentHeader")
                                .SetParent<Header>()
                                .SetGroupName("Network")
                                .AddConstructor<ExperimentHeader>();
        return tid;
    }

    TypeId GetInstanceTypeId() const override
    {
        return GetTypeId();
    }

    uint32_t GetSerializedSize() const override
    {
        return 20;
    }

    void Serialize(Buffer::Iterator start) const override
    {
        start.WriteHtonU32(kWireHeaderMagic);
        start.WriteU8(static_cast<uint8_t>(m_flow));
        start.WriteU8(0);
        start.WriteU8(0);
        start.WriteU8(0);
        start.WriteHtonU32(m_sequence);
        start.WriteHtonU64(m_sendTimestampNs);
    }

    uint32_t Deserialize(Buffer::Iterator start) override
    {
        m_magic = start.ReadNtohU32();
        m_flow = static_cast<FlowKind>(start.ReadU8());
        start.ReadU8();
        start.ReadU8();
        start.ReadU8();
        m_sequence = start.ReadNtohU32();
        m_sendTimestampNs = start.ReadNtohU64();
        return GetSerializedSize();
    }

    void Print(std::ostream& os) const override
    {
        os << "flow=" << static_cast<uint32_t>(m_flow) << " seq=" << m_sequence
           << " tx_ns=" << m_sendTimestampNs;
    }

    void Set(FlowKind flow, uint32_t sequence, uint64_t sendTimestampNs)
    {
        m_magic = kWireHeaderMagic;
        m_flow = flow;
        m_sequence = sequence;
        m_sendTimestampNs = sendTimestampNs;
    }

    bool IsValid() const
    {
        return m_magic == kWireHeaderMagic &&
               (m_flow == FlowKind::CONTROL || m_flow == FlowKind::SENSOR ||
                m_flow == FlowKind::BULK);
    }

    FlowKind GetFlow() const
    {
        return m_flow;
    }

    uint32_t GetSequence() const
    {
        return m_sequence;
    }

    uint64_t GetSendTimestampNs() const
    {
        return m_sendTimestampNs;
    }

  private:
    uint32_t m_magic{kWireHeaderMagic};
    FlowKind m_flow{FlowKind::CONTROL};
    uint32_t m_sequence{0};
    uint64_t m_sendTimestampNs{0};
};

NS_OBJECT_ENSURE_REGISTERED(ExperimentHeader);

/**
 * A two-band, non-preemptive strict-priority queue disc with one aggregate
 * byte limit.  A non-zero SocketPriorityTag selects the high band.  The
 * scenario marks only control packets (DSCP EF), so sensor and bulk packets
 * share the low FIFO band.  The currently transmitting packet is not
 * preempted, matching ordinary packet schedulers.
 */
class ResearchStrictPriorityQueueDisc : public QueueDisc
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::ResearchStrictPriorityQueueDisc")
                                .SetParent<QueueDisc>()
                                .SetGroupName("TrafficControl")
                                .AddConstructor<ResearchStrictPriorityQueueDisc>()
                                .AddAttribute("MaxSize",
                                              "Aggregate byte capacity across both bands.",
                                              QueueSizeValue(QueueSize("150000B")),
                                              MakeQueueSizeAccessor(&QueueDisc::SetMaxSize,
                                                                    &QueueDisc::GetMaxSize),
                                              MakeQueueSizeChecker());
        return tid;
    }

    ResearchStrictPriorityQueueDisc()
        : QueueDisc(QueueDiscSizePolicy::MULTIPLE_QUEUES, QueueSizeUnit::BYTES)
    {
    }

    ~ResearchStrictPriorityQueueDisc() override = default;

  private:
    static constexpr const char* LIMIT_EXCEEDED_DROP = "Aggregate byte limit exceeded";

    bool DoEnqueue(Ptr<QueueDiscItem> item) override
    {
        if (GetCurrentSize() + item > GetMaxSize())
        {
            DropBeforeEnqueue(item, LIMIT_EXCEEDED_DROP);
            return false;
        }

        SocketPriorityTag priorityTag;
        const bool highPriority = item->GetPacket()->PeekPacketTag(priorityTag) &&
                                  priorityTag.GetPriority() != 0;
        return GetInternalQueue(highPriority ? 0 : 1)->Enqueue(item);
    }

    Ptr<QueueDiscItem> DoDequeue() override
    {
        Ptr<QueueDiscItem> item = GetInternalQueue(0)->Dequeue();
        return item ? item : GetInternalQueue(1)->Dequeue();
    }

    Ptr<const QueueDiscItem> DoPeek() override
    {
        Ptr<const QueueDiscItem> item = GetInternalQueue(0)->Peek();
        return item ? item : GetInternalQueue(1)->Peek();
    }

    bool CheckConfig() override
    {
        if (GetNQueueDiscClasses() != 0 || GetNPacketFilters() != 0)
        {
            return false;
        }
        if (GetNInternalQueues() == 0)
        {
            for (uint32_t band = 0; band < 2; ++band)
            {
                AddInternalQueue(CreateObjectWithAttributes<DropTailQueue<QueueDiscItem>>(
                    "MaxSize",
                    QueueSizeValue(GetMaxSize())));
            }
        }
        if (GetNInternalQueues() != 2)
        {
            return false;
        }
        return GetInternalQueue(0)->GetMaxSize().GetUnit() == QueueSizeUnit::BYTES &&
               GetInternalQueue(1)->GetMaxSize().GetUnit() == QueueSizeUnit::BYTES;
    }

    void InitializeParams() override
    {
    }
};

NS_OBJECT_ENSURE_REGISTERED(ResearchStrictPriorityQueueDisc);

class ScheduledUdpSource : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::ScheduledUdpSource")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<ScheduledUdpSource>();
        return tid;
    }

    void Configure(Ipv4Address destination,
                   uint16_t port,
                   FlowKind flow,
                   uint32_t totalIpBytes,
                   uint8_t ipTos,
                   std::vector<Emission> emissions,
                   std::map<uint32_t, bool>* sendStatus)
    {
        if (totalIpBytes < kIpv4UdpHeaderBytes + ExperimentHeader().GetSerializedSize())
        {
            throw std::invalid_argument("IP packet is too small for UDP and experiment headers");
        }
        m_destination = destination;
        m_port = port;
        m_flow = flow;
        m_totalIpBytes = totalIpBytes;
        m_ipTos = ipTos;
        m_emissions = std::move(emissions);
        m_sendStatus = sendStatus;
    }

  private:
    void StartApplication() override
    {
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        if (m_socket->Bind() != 0)
        {
            throw std::runtime_error("UDP source bind failed");
        }
        m_socket->SetIpTos(m_ipTos);
        if (m_socket->Connect(InetSocketAddress(m_destination, m_port)) != 0)
        {
            throw std::runtime_error("UDP source connect failed");
        }
        m_next = 0;
        ScheduleNext();
    }

    void StopApplication() override
    {
        if (m_sendEvent.IsPending())
        {
            Simulator::Cancel(m_sendEvent);
        }
        if (m_socket)
        {
            m_socket->Close();
            m_socket = nullptr;
        }
    }

    void ScheduleNext()
    {
        if (m_next >= m_emissions.size())
        {
            return;
        }
        const Time at = Seconds(m_emissions[m_next].timeSeconds);
        const Time delay = at > Simulator::Now() ? at - Simulator::Now() : TimeStep(0);
        m_sendEvent = Simulator::Schedule(delay, &ScheduledUdpSource::SendOne, this);
    }

    void SendOne()
    {
        const Emission emission = m_emissions.at(m_next);
        ExperimentHeader header;
        header.Set(m_flow, emission.sequence, Simulator::Now().GetNanoSeconds());
        const uint32_t udpPayloadBytes = m_totalIpBytes - kIpv4UdpHeaderBytes;
        Ptr<Packet> packet =
            Create<Packet>(udpPayloadBytes - header.GetSerializedSize());
        packet->AddHeader(header);
        const int acceptedBytes = m_socket->Send(packet);
        if (m_sendStatus)
        {
            (*m_sendStatus)[emission.sequence] =
                acceptedBytes == static_cast<int>(udpPayloadBytes);
        }
        ++m_next;
        ScheduleNext();
    }

    Ptr<Socket> m_socket;
    EventId m_sendEvent;
    Ipv4Address m_destination;
    uint16_t m_port{0};
    FlowKind m_flow{FlowKind::CONTROL};
    uint32_t m_totalIpBytes{0};
    uint8_t m_ipTos{0};
    std::vector<Emission> m_emissions;
    std::size_t m_next{0};
    std::map<uint32_t, bool>* m_sendStatus{nullptr};
};

NS_OBJECT_ENSURE_REGISTERED(ScheduledUdpSource);

class MeasurementSink : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::BurstTailMeasurementSink")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<MeasurementSink>();
        return tid;
    }

    void Configure(uint16_t port,
                   double measurementStart,
                   double measurementEnd,
                   uint32_t controlIpBytes,
                   uint32_t sensorIpBytes,
                   uint32_t bulkIpBytes)
    {
        m_port = port;
        m_measurementStart = measurementStart;
        m_measurementEnd = measurementEnd;
        m_ipBytes = {controlIpBytes, sensorIpBytes, bulkIpBytes};
    }

    const std::map<uint32_t, Reception>& GetControlReceptions() const
    {
        return m_controlReceptions;
    }

    uint64_t GetMeasuredDeliveredPackets(FlowKind flow) const
    {
        return m_deliveredPackets.at(static_cast<std::size_t>(flow) - 1);
    }

    uint64_t GetMeasuredDeliveredIpBytes(FlowKind flow) const
    {
        return m_deliveredIpBytes.at(static_cast<std::size_t>(flow) - 1);
    }

  private:
    void StartApplication() override
    {
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        if (m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), m_port)) != 0)
        {
            throw std::runtime_error("measurement sink bind failed");
        }
        m_socket->SetRecvCallback(MakeCallback(&MeasurementSink::HandleRead, this));
    }

    void StopApplication() override
    {
        if (m_socket)
        {
            m_socket->SetRecvCallback(MakeNullCallback<void, Ptr<Socket>>());
            m_socket->Close();
            m_socket = nullptr;
        }
    }

    void HandleRead(Ptr<Socket> socket)
    {
        Address from;
        while (Ptr<Packet> packet = socket->RecvFrom(from))
        {
            if (packet->GetSize() < ExperimentHeader().GetSerializedSize())
            {
                continue;
            }
            ExperimentHeader header;
            packet->RemoveHeader(header);
            if (!header.IsValid())
            {
                continue;
            }
            const double sendTime =
                static_cast<double>(header.GetSendTimestampNs()) * 1e-9;
            if (sendTime + kTolerance < m_measurementStart ||
                sendTime >= m_measurementEnd - kTolerance)
            {
                continue;
            }
            const std::size_t index = static_cast<std::size_t>(header.GetFlow()) - 1;
            ++m_deliveredPackets.at(index);
            m_deliveredIpBytes.at(index) += m_ipBytes.at(index);
            if (header.GetFlow() == FlowKind::CONTROL)
            {
                const double receiveTime = Simulator::Now().GetSeconds();
                const auto [it, inserted] = m_controlReceptions.emplace(
                    header.GetSequence(),
                    Reception{receiveTime, receiveTime - sendTime});
                if (!inserted)
                {
                    throw std::runtime_error("duplicate measured control sequence received");
                }
            }
        }
    }

    Ptr<Socket> m_socket;
    uint16_t m_port{0};
    double m_measurementStart{0.0};
    double m_measurementEnd{0.0};
    std::array<uint32_t, 3> m_ipBytes{};
    std::array<uint64_t, 3> m_deliveredPackets{};
    std::array<uint64_t, 3> m_deliveredIpBytes{};
    std::map<uint32_t, Reception> m_controlReceptions;
};

NS_OBJECT_ENSURE_REGISTERED(MeasurementSink);

uint64_t
SplitMix64(uint64_t value)
{
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

double
PairedUniform01(uint32_t seed, uint64_t run, uint64_t salt)
{
    const uint64_t mixed = SplitMix64((static_cast<uint64_t>(seed) << 32) ^ run ^ salt);
    return static_cast<double>(mixed >> 11) * (1.0 / 9007199254740992.0);
}

void
Require(bool condition, const std::string& message)
{
    if (!condition)
    {
        throw std::invalid_argument(message);
    }
}

bool
IsIntegerRatio(double numerator, double denominator)
{
    const double ratio = numerator / denominator;
    return std::abs(ratio - std::round(ratio)) <=
           kTolerance * std::max(1.0, std::abs(ratio));
}

std::vector<Emission>
BuildPeriodicEmissions(double start,
                       double period,
                       uint32_t count,
                       uint32_t firstSequence = 0)
{
    std::vector<Emission> result;
    result.reserve(count);
    for (uint32_t index = 0; index < count; ++index)
    {
        result.push_back({start + static_cast<double>(index) * period,
                          firstSequence + index});
    }
    return result;
}

std::vector<Emission>
BuildBurstEmissions(double start,
                    double end,
                    double referenceStart,
                    double phaseSeconds,
                    double cycleSeconds,
                    double onDurationSeconds,
                    double onRateBps,
                    uint32_t totalIpBytes,
                    double latticeFraction)
{
    const double packetBits = static_cast<double>(totalIpBytes) * 8.0;
    const double origin = referenceStart - phaseSeconds;
    const int64_t firstCycle =
        static_cast<int64_t>(std::floor((start - origin) / cycleSeconds)) - 1;
    const int64_t lastCycle =
        static_cast<int64_t>(std::ceil((end - origin) / cycleSeconds)) + 1;

    std::vector<Emission> result;
    double cumulativeBits = 0.0;
    uint32_t nextSequence = 0;
    double nextThresholdBits = latticeFraction * packetBits;
    for (int64_t cycle = firstCycle; cycle <= lastCycle; ++cycle)
    {
        const double onStart = origin + static_cast<double>(cycle) * cycleSeconds;
        const double intervalStart = std::max(start, onStart);
        const double intervalEnd = std::min(end, onStart + onDurationSeconds);
        if (intervalEnd <= intervalStart + kTolerance)
        {
            continue;
        }
        const double intervalBits = (intervalEnd - intervalStart) * onRateBps;
        while (nextThresholdBits <= cumulativeBits + intervalBits + 1e-6)
        {
            const double at = intervalStart +
                              (nextThresholdBits - cumulativeBits) / onRateBps;
            if (at >= start - kTolerance && at < end - kTolerance)
            {
                result.push_back({std::max(start, at), nextSequence});
            }
            ++nextSequence;
            nextThresholdBits = (static_cast<double>(nextSequence) + latticeFraction) * packetBits;
        }
        cumulativeBits += intervalBits;
    }
    return result;
}

double
PercentileR7(std::vector<double> values, double probability)
{
    if (values.empty())
    {
        return std::numeric_limits<double>::quiet_NaN();
    }
    std::sort(values.begin(), values.end());
    const double position = (static_cast<double>(values.size()) - 1.0) * probability;
    const std::size_t lower = static_cast<std::size_t>(std::floor(position));
    const std::size_t upper = static_cast<std::size_t>(std::ceil(position));
    if (lower == upper)
    {
        return values.at(lower);
    }
    const double fraction = position - static_cast<double>(lower);
    return values.at(lower) * (1.0 - fraction) + values.at(upper) * fraction;
}

double
ServiceFactorAt(double time,
                double referenceStart,
                double phaseSeconds,
                double dwellSeconds,
                double lowFactor,
                double highFactor)
{
    const double cycle = 2.0 * dwellSeconds;
    double position = std::fmod(time - referenceStart + phaseSeconds, cycle);
    if (position < 0.0)
    {
        position += cycle;
    }
    return position < dwellSeconds ? lowFactor : highFactor;
}

double
IntegrateServiceFactor(double start,
                       double end,
                       double referenceStart,
                       double phaseSeconds,
                       double dwellSeconds,
                       double lowFactor,
                       double highFactor)
{
    double current = start;
    double integral = 0.0;
    const double cycle = 2.0 * dwellSeconds;
    while (current < end - kTolerance)
    {
        double position = std::fmod(current - referenceStart + phaseSeconds, cycle);
        if (position < 0.0)
        {
            position += cycle;
        }
        const bool low = position < dwellSeconds;
        const double statePosition = low ? position : position - dwellSeconds;
        const double width = std::min(end - current, dwellSeconds - statePosition);
        integral += width * (low ? lowFactor : highFactor);
        current += width;
        if (width <= kTolerance)
        {
            current += kTolerance;
        }
    }
    return integral;
}

void
ChangeServiceState(Ptr<PointToPointNetDevice> device,
                   uint64_t lowRate,
                   uint64_t highRate,
                   bool useLow,
                   double dwellSeconds,
                   double endSeconds)
{
    device->SetDataRate(DataRate(useLow ? lowRate : highRate));
    const double next = Simulator::Now().GetSeconds() + dwellSeconds;
    if (next < endSeconds - kTolerance)
    {
        Simulator::Schedule(Seconds(dwellSeconds),
                            &ChangeServiceState,
                            device,
                            lowRate,
                            highRate,
                            !useLow,
                            dwellSeconds,
                            endSeconds);
    }
}

void
ConfigureAlternatingService(Ptr<PointToPointNetDevice> device,
                            double referenceStart,
                            double phaseSeconds,
                            double dwellSeconds,
                            uint64_t meanRate,
                            double lowFactor,
                            double highFactor,
                            double endSeconds)
{
    const uint64_t lowRate =
        static_cast<uint64_t>(std::llround(static_cast<double>(meanRate) * lowFactor));
    const uint64_t highRate =
        static_cast<uint64_t>(std::llround(static_cast<double>(meanRate) * highFactor));
    const double cycle = 2.0 * dwellSeconds;
    double position = std::fmod(phaseSeconds, cycle);
    if (position < 0.0)
    {
        position += cycle;
    }
    const bool initiallyLow = position < dwellSeconds;
    const double statePosition = initiallyLow ? position : position - dwellSeconds;
    const double untilBoundary = dwellSeconds - statePosition;
    device->SetDataRate(DataRate(initiallyLow ? lowRate : highRate));
    const double boundary = referenceStart + untilBoundary;
    if (boundary < endSeconds - kTolerance)
    {
        Simulator::Schedule(Seconds(boundary),
                            &ChangeServiceState,
                            device,
                            lowRate,
                            highRate,
                            !initiallyLow,
                            dwellSeconds,
                            endSeconds);
    }
}

std::string
CsvNumber(double value)
{
    if (!std::isfinite(value))
    {
        return "";
    }
    std::ostringstream stream;
    stream << std::setprecision(17) << value;
    return stream.str();
}

void
EnsureNewOutputPath(const std::filesystem::path& path)
{
    Require(!path.empty(), "output path must not be empty");
    if (std::filesystem::exists(path))
    {
        throw std::invalid_argument("refusing to overwrite existing output: " + path.string());
    }
    if (path.has_parent_path())
    {
        std::filesystem::create_directories(path.parent_path());
    }
}

int
RunScenario(int argc, char* argv[])
{
    uint32_t seed = 20260925;
    uint64_t run = 1;
    double rho = 0.60;
    double pmr = 3.0;
    double tauBPeriods = 5.0;
    std::string queueMode = "fifo";
    std::string serviceMode = "constant";
    double serviceDwellPeriods = 5.0;
    double serviceLowFactor = 0.70;
    double serviceHighFactor = 1.30;
    double controlPeriodMs = 20.0;
    double sensorPeriodPeriods = 2.0;
    double deadlinePeriods = 1.0;
    uint32_t warmupControlPackets = 1000;
    uint32_t measuredControlPackets = 10000;
    uint64_t bottleneckBps = 6000000;
    uint64_t accessBps = 100000000;
    double accessDelayMs = 0.05;
    double bottleneckDelayMs = 0.20;
    uint32_t controlIpBytes = 150;
    uint32_t sensorIpBytes = 600;
    uint32_t bulkIpBytes = 1500;
    uint32_t bufferBytes = 150000;
    double drainSeconds = 1.0;
    std::string summaryCsv = "ns3_summary.csv";
    std::string packetCsv = "ns3_control_packets.csv";

    CommandLine command(__FILE__);
    command.AddValue("seed", "ns-3 RNG seed and deterministic phase seed", seed);
    command.AddValue("run", "ns-3 RNG run and deterministic phase run", run);
    command.AddValue("rho", "target aggregate IP offered load / nominal mean service", rho);
    command.AddValue("R", "bulk peak-to-mean rate ratio (>= 1)", pmr);
    command.AddValue("tauB", "bulk ON/OFF cycle length divided by control period", tauBPeriods);
    command.AddValue("queue", "bottleneck qdisc: fifo, priority or fq_codel", queueMode);
    command.AddValue("service", "bottleneck service: constant or alternating", serviceMode);
    command.AddValue("tauS", "one low/high service dwell divided by control period", serviceDwellPeriods);
    command.AddValue("serviceLow", "alternating-service low-rate factor", serviceLowFactor);
    command.AddValue("serviceHigh", "alternating-service high-rate factor", serviceHighFactor);
    command.AddValue("controlPeriodMs", "control period in milliseconds", controlPeriodMs);
    command.AddValue("sensorPeriodPeriods", "sensor period divided by control period", sensorPeriodPeriods);
    command.AddValue("deadlinePeriods", "normalized control deadline", deadlinePeriods);
    command.AddValue("warmupControlPackets", "warm-up control periods", warmupControlPackets);
    command.AddValue("measuredControlPackets", "measured control cohort size", measuredControlPackets);
    command.AddValue("bottleneckBps", "nominal mean bottleneck bit rate", bottleneckBps);
    command.AddValue("accessBps", "source access-link bit rate", accessBps);
    command.AddValue("accessDelayMs", "one-way source access-link delay", accessDelayMs);
    command.AddValue("bottleneckDelayMs", "one-way bottleneck propagation delay", bottleneckDelayMs);
    command.AddValue("controlIpBytes", "total control IPv4 packet size", controlIpBytes);
    command.AddValue("sensorIpBytes", "total sensor IPv4 packet size", sensorIpBytes);
    command.AddValue("bulkIpBytes", "total bulk IPv4 packet size", bulkIpBytes);
    command.AddValue("bufferBytes", "aggregate bottleneck qdisc capacity", bufferBytes);
    command.AddValue("drainSeconds", "no-new-arrival drain after observation", drainSeconds);
    // Preserve spaces in native Windows paths; generic string extraction stops
    // at whitespace even when the shell correctly quotes the argument.
    command.AddValue("summaryCsv", "new summary CSV path",
                     Callback<bool, const std::string&>([&summaryCsv](const std::string& value) {
                         summaryCsv = value;
                         return !value.empty();
                     }));
    command.AddValue("packetCsv", "new measured-control packet CSV path",
                     Callback<bool, const std::string&>([&packetCsv](const std::string& value) {
                         packetCsv = value;
                         return !value.empty();
                     }));
    command.Parse(argc, argv);

    Require(seed > 0, "seed must be positive");
    Require(run > 0, "run must be positive");
    Require(std::isfinite(rho) && rho > 0.0, "rho must be positive and finite");
    Require(std::isfinite(pmr) && pmr >= 1.0, "R must be finite and at least 1");
    Require(std::isfinite(tauBPeriods) && tauBPeriods > 0.0, "tauB must be positive");
    Require(queueMode == "fifo" || queueMode == "fifo_packet" || queueMode == "priority" || queueMode == "fq_codel",
            "queue must be fifo, fifo_packet, priority or fq_codel");
    Require(serviceMode == "constant" || serviceMode == "alternating",
            "service must be constant or alternating");
    Require(controlPeriodMs > 0.0 && sensorPeriodPeriods > 0.0 && deadlinePeriods > 0.0,
            "periods and deadline must be positive");
    Require(warmupControlPackets > 0 && measuredControlPackets > 0,
            "warm-up and measured cohort sizes must be positive");
    Require(bottleneckBps > 0 && accessBps > 0, "link rates must be positive");
    Require(accessDelayMs >= 0.0 && bottleneckDelayMs >= 0.0,
            "link delays must be non-negative");
    Require(controlIpBytes <= 65507 + kIpv4UdpHeaderBytes &&
                sensorIpBytes <= 65507 + kIpv4UdpHeaderBytes &&
                bulkIpBytes <= 65507 + kIpv4UdpHeaderBytes,
            "IP packet size exceeds UDP/IPv4 limit");
    const uint32_t experimentHeaderBytes = ExperimentHeader().GetSerializedSize();
    Require(controlIpBytes >= kIpv4UdpHeaderBytes + experimentHeaderBytes &&
                sensorIpBytes >= kIpv4UdpHeaderBytes + experimentHeaderBytes &&
                bulkIpBytes >= kIpv4UdpHeaderBytes + experimentHeaderBytes,
            "each IP packet must fit UDP and the 20-byte experiment header");
    Require(bufferBytes >= bulkIpBytes, "buffer must fit at least one bulk packet");
    Require(summaryCsv != packetCsv, "summaryCsv and packetCsv must differ");
    Require(IsIntegerRatio(warmupControlPackets, tauBPeriods) &&
                IsIntegerRatio(measuredControlPackets, tauBPeriods),
            "warm-up and measurement windows must each contain whole tauB cycles");
    Require(IsIntegerRatio(warmupControlPackets, sensorPeriodPeriods) &&
                IsIntegerRatio(measuredControlPackets, sensorPeriodPeriods),
            "warm-up and measurement windows must each contain whole sensor periods");
    if (serviceMode == "alternating")
    {
        Require(serviceDwellPeriods > 0.0 && serviceLowFactor > 0.0 &&
                    serviceHighFactor > 0.0,
                "alternating service parameters must be positive");
        Require(std::abs((serviceLowFactor + serviceHighFactor) / 2.0 - 1.0) <= 1e-12,
                "serviceLow and serviceHigh must have arithmetic mean 1");
        Require(IsIntegerRatio(warmupControlPackets, 2.0 * serviceDwellPeriods) &&
                    IsIntegerRatio(measuredControlPackets, 2.0 * serviceDwellPeriods),
                "warm-up and measurement windows must each contain whole service cycles");
    }

    const double controlPeriod = controlPeriodMs * 1e-3;
    const double sensorPeriod = sensorPeriodPeriods * controlPeriod;
    const double trafficStart = 1.0;
    const double measurementStart =
        trafficStart + static_cast<double>(warmupControlPackets) * controlPeriod;
    const double measurementDuration =
        static_cast<double>(measuredControlPackets) * controlPeriod;
    const double measurementEnd = measurementStart + measurementDuration;
    const double deadline = deadlinePeriods * controlPeriod;
    const double burstCycle = tauBPeriods * controlPeriod;
    const double burstOnDuration = burstCycle / pmr;
    const double serviceDwell = serviceDwellPeriods * controlPeriod;

    const double targetControlBps = static_cast<double>(controlIpBytes) * 8.0 /
                                    controlPeriod;
    const double targetSensorBps = static_cast<double>(sensorIpBytes) * 8.0 /
                                   sensorPeriod;
    const double targetBulkBps = rho * static_cast<double>(bottleneckBps) -
                                 targetControlBps - targetSensorBps;
    Require(targetBulkBps > 0.0,
            "rho is below the fixed control+sensor offered-load floor");
    const double bulkOnRateBps = pmr * targetBulkBps;
    Require(bulkOnRateBps <= 0.95 * static_cast<double>(accessBps),
            "bulk ON rate exceeds 95% of access rate; raise accessBps or lower R/rho");

    const double minimumServiceFactor =
        serviceMode == "alternating" ? std::min(serviceLowFactor, serviceHighFactor) : 1.0;
    const uint32_t maxPacketBytes = std::max({controlIpBytes, sensorIpBytes, bulkIpBytes});
    const double conservativeDrain =
        (static_cast<double>(bufferBytes) + 3.0 * maxPacketBytes) * 8.0 /
            (static_cast<double>(bottleneckBps) * minimumServiceFactor) +
        3.0 * accessDelayMs * 1e-3 + bottleneckDelayMs * 1e-3 + controlPeriod;
    Require(drainSeconds + kTolerance >= conservativeDrain,
            "drainSeconds is too short for the configured finite queue and minimum service rate");
    const double simulationEnd = measurementEnd + drainSeconds;

    const std::filesystem::path summaryPath(summaryCsv);
    const std::filesystem::path packetPath(packetCsv);
    EnsureNewOutputPath(summaryPath);
    EnsureNewOutputPath(packetPath);

    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(run);

    const double bulkPhaseFraction = PairedUniform01(seed, run, 0x42554c4bULL);
    const double bulkLatticeFraction = 1.0 - PairedUniform01(seed, run, 0x4c415454ULL);
    const double servicePhaseFraction = PairedUniform01(seed, run, 0x53455256ULL);
    const double bulkPhaseSeconds = bulkPhaseFraction * burstCycle;
    const double servicePhaseSeconds = serviceMode == "alternating"
                                           ? servicePhaseFraction * 2.0 * serviceDwell
                                           : 0.0;

    const uint32_t totalControlPackets = warmupControlPackets + measuredControlPackets;
    std::vector<Emission> controlEmissions =
        BuildPeriodicEmissions(trafficStart, controlPeriod, totalControlPackets);
    const uint32_t totalSensorPackets = static_cast<uint32_t>(std::llround(
        (static_cast<double>(warmupControlPackets + measuredControlPackets)) /
        sensorPeriodPeriods));
    std::vector<Emission> sensorEmissions =
        BuildPeriodicEmissions(trafficStart, sensorPeriod, totalSensorPackets);
    std::vector<Emission> bulkEmissions = BuildBurstEmissions(trafficStart,
                                                               measurementEnd,
                                                               trafficStart,
                                                               bulkPhaseSeconds,
                                                               burstCycle,
                                                               burstOnDuration,
                                                               bulkOnRateBps,
                                                               bulkIpBytes,
                                                               bulkLatticeFraction);

    const auto countMeasured = [measurementStart, measurementEnd](
                                   const std::vector<Emission>& emissions) {
        return static_cast<uint64_t>(std::count_if(
            emissions.begin(),
            emissions.end(),
            [measurementStart, measurementEnd](const Emission& emission) {
                return emission.timeSeconds >= measurementStart - kTolerance &&
                       emission.timeSeconds < measurementEnd - kTolerance;
            }));
    };
    const uint64_t measuredControlGenerated = countMeasured(controlEmissions);
    const uint64_t measuredSensorGenerated = countMeasured(sensorEmissions);
    const uint64_t measuredBulkGenerated = countMeasured(bulkEmissions);
    Require(measuredControlGenerated == measuredControlPackets,
            "internal error: measured control cohort is incomplete");

    const double realizedControlBps =
        measuredControlGenerated * static_cast<double>(controlIpBytes) * 8.0 /
        measurementDuration;
    const double realizedSensorBps =
        measuredSensorGenerated * static_cast<double>(sensorIpBytes) * 8.0 /
        measurementDuration;
    const double realizedBulkBps =
        measuredBulkGenerated * static_cast<double>(bulkIpBytes) * 8.0 /
        measurementDuration;
    const double realizedOfferedLoad =
        (realizedControlBps + realizedSensorBps + realizedBulkBps) /
        static_cast<double>(bottleneckBps);

    NodeContainer controlNode;
    NodeContainer sensorNode;
    NodeContainer bulkNode;
    NodeContainer routerNode;
    NodeContainer sinkNode;
    controlNode.Create(1);
    sensorNode.Create(1);
    bulkNode.Create(1);
    routerNode.Create(1);
    sinkNode.Create(1);

    NodeContainer allNodes(controlNode.Get(0),
                           sensorNode.Get(0),
                           bulkNode.Get(0),
                           routerNode.Get(0),
                           sinkNode.Get(0));
    InternetStackHelper internet;
    internet.Install(allNodes);

    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", DataRateValue(DataRate(accessBps)));
    access.SetChannelAttribute("Delay", TimeValue(MilliSeconds(accessDelayMs)));
    access.SetQueue("ns3::DropTailQueue", "MaxSize", StringValue("20p"));
    NetDeviceContainer controlAccess = access.Install(controlNode.Get(0), routerNode.Get(0));
    NetDeviceContainer sensorAccess = access.Install(sensorNode.Get(0), routerNode.Get(0));
    NetDeviceContainer bulkAccess = access.Install(bulkNode.Get(0), routerNode.Get(0));

    PointToPointHelper bottleneck;
    bottleneck.SetDeviceAttribute("DataRate", DataRateValue(DataRate(bottleneckBps)));
    bottleneck.SetChannelAttribute("Delay", TimeValue(MilliSeconds(bottleneckDelayMs)));
    bottleneck.SetQueue("ns3::DropTailQueue", "MaxSize", StringValue("1p"));
    NetDeviceContainer bottleneckDevices =
        bottleneck.Install(routerNode.Get(0), sinkNode.Get(0));

    TrafficControlHelper bottleneckTc;
    const QueueSize byteLimit(std::to_string(bufferBytes) + "B");
    if (queueMode == "fifo" || queueMode == "fifo_packet")
    {
        bottleneckTc.SetRootQueueDisc("ns3::FifoQueueDisc",
                                      "MaxSize",
                                      QueueSizeValue(queueMode == "fifo" ? byteLimit : QueueSize("100p")));
    }
    else if (queueMode == "priority")
    {
        bottleneckTc.SetRootQueueDisc("ns3::ResearchStrictPriorityQueueDisc",
                                      "MaxSize",
                                      QueueSizeValue(byteLimit));
    }
    else
    {
        bottleneckTc.SetRootQueueDisc("ns3::FqCoDelQueueDisc",
                                      "MaxSize", QueueSizeValue(QueueSize("100p")),
                                      "UseEcn", BooleanValue(false),
                                      "Target", StringValue("5ms"),
                                      "Interval", StringValue("100ms"),
                                      "Perturbation", UintegerValue(0));
    }
    QueueDiscContainer rootQueue = bottleneckTc.Install(bottleneckDevices.Get(0));
    Require(rootQueue.GetN() == 1, "failed to install exactly one bottleneck qdisc");

    Ipv4AddressHelper address;
    address.SetBase("10.1.1.0", "255.255.255.0");
    address.Assign(controlAccess);
    address.SetBase("10.1.2.0", "255.255.255.0");
    address.Assign(sensorAccess);
    address.SetBase("10.1.3.0", "255.255.255.0");
    address.Assign(bulkAccess);
    address.SetBase("10.1.4.0", "255.255.255.0");
    const Ipv4InterfaceContainer bottleneckInterfaces = address.Assign(bottleneckDevices);
    const Ipv4Address sinkAddress = bottleneckInterfaces.GetAddress(1);
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    Ptr<PointToPointNetDevice> routerBottleneck =
        DynamicCast<PointToPointNetDevice>(bottleneckDevices.Get(0));
    Require(routerBottleneck != nullptr, "router bottleneck device is not point-to-point");
    if (serviceMode == "alternating")
    {
        ConfigureAlternatingService(routerBottleneck,
                                    trafficStart,
                                    servicePhaseSeconds,
                                    serviceDwell,
                                    bottleneckBps,
                                    serviceLowFactor,
                                    serviceHighFactor,
                                    simulationEnd);
    }

    Ptr<MeasurementSink> sink = CreateObject<MeasurementSink>();
    sink->Configure(kSinkPort,
                    measurementStart,
                    measurementEnd,
                    controlIpBytes,
                    sensorIpBytes,
                    bulkIpBytes);
    sinkNode.Get(0)->AddApplication(sink);
    sink->SetStartTime(Seconds(0.0));

    std::map<uint32_t, bool> controlSendStatus;
    Ptr<ScheduledUdpSource> controlSource = CreateObject<ScheduledUdpSource>();
    // EF survives IPv4 forwarding as a non-zero socket-priority tag.
    controlSource->Configure(sinkAddress,
                             kSinkPort,
                             FlowKind::CONTROL,
                             controlIpBytes,
                             0xb8,
                             std::move(controlEmissions),
                             &controlSendStatus);
    controlNode.Get(0)->AddApplication(controlSource);
    controlSource->SetStartTime(Seconds(trafficStart));
    controlSource->SetStopTime(Seconds(measurementEnd));

    Ptr<ScheduledUdpSource> sensorSource = CreateObject<ScheduledUdpSource>();
    sensorSource->Configure(sinkAddress,
                            kSinkPort,
                            FlowKind::SENSOR,
                            sensorIpBytes,
                            0,
                            std::move(sensorEmissions),
                            nullptr);
    sensorNode.Get(0)->AddApplication(sensorSource);
    sensorSource->SetStartTime(Seconds(trafficStart));
    sensorSource->SetStopTime(Seconds(measurementEnd));

    Ptr<ScheduledUdpSource> bulkSource = CreateObject<ScheduledUdpSource>();
    bulkSource->Configure(sinkAddress,
                          kSinkPort,
                          FlowKind::BULK,
                          bulkIpBytes,
                          0,
                          std::move(bulkEmissions),
                          nullptr);
    bulkNode.Get(0)->AddApplication(bulkSource);
    bulkSource->SetStartTime(Seconds(trafficStart));
    bulkSource->SetStopTime(Seconds(measurementEnd));

    Simulator::Stop(Seconds(simulationEnd));
    Simulator::Run();

    const auto& receptions = sink->GetControlReceptions();
    std::vector<double> deliveredLatencies;
    deliveredLatencies.reserve(measuredControlPackets);
    uint64_t sourceAccepted = 0;
    uint64_t misses = 0;
    uint64_t delivered = 0;

    std::ofstream packetOutput(packetPath, std::ios::out | std::ios::trunc);
    if (!packetOutput)
    {
        throw std::runtime_error("cannot open packet CSV: " + packetPath.string());
    }
    packetOutput << "schema_version,seed,run,rho,R,tauB_periods,queue_mode,service_mode,"
                    "control_sequence,send_time_s,source_send_ok,delivered,receive_time_s,"
                    "latency_s,latency_over_T,deadline_miss,terminal_status\n";
    packetOutput << std::setprecision(17);
    for (uint32_t measuredIndex = 0; measuredIndex < measuredControlPackets; ++measuredIndex)
    {
        const uint32_t sequence = warmupControlPackets + measuredIndex;
        const double sendTime = measurementStart + measuredIndex * controlPeriod;
        const auto sendIt = controlSendStatus.find(sequence);
        const bool sentOk = sendIt != controlSendStatus.end() && sendIt->second;
        sourceAccepted += sentOk ? 1 : 0;
        const auto receiveIt = receptions.find(sequence);
        const bool wasDelivered = receiveIt != receptions.end();
        bool miss = true;
        std::string receiveTime;
        std::string latency;
        std::string normalizedLatency;
        std::string status;
        if (wasDelivered)
        {
            ++delivered;
            deliveredLatencies.push_back(receiveIt->second.latencySeconds);
            miss = receiveIt->second.latencySeconds >= deadline;
            receiveTime = CsvNumber(receiveIt->second.receiveTimeSeconds);
            latency = CsvNumber(receiveIt->second.latencySeconds);
            normalizedLatency =
                CsvNumber(receiveIt->second.latencySeconds / controlPeriod);
            status = "delivered";
        }
        else if (!sentOk)
        {
            status = "source_send_failed";
        }
        else
        {
            status = "undelivered_after_drain";
        }
        misses += miss ? 1 : 0;
        packetOutput << "1," << seed << ',' << run << ',' << rho << ',' << pmr << ','
                     << tauBPeriods << ',' << queueMode << ',' << serviceMode << ','
                     << sequence << ',' << sendTime << ',' << (sentOk ? 1 : 0) << ','
                     << (wasDelivered ? 1 : 0) << ',' << receiveTime << ',' << latency << ','
                     << normalizedLatency << ',' << (miss ? 1 : 0) << ',' << status << '\n';
    }
    packetOutput.close();
    if (!packetOutput)
    {
        throw std::runtime_error("failed while writing packet CSV: " + packetPath.string());
    }

    const double p99 = PercentileR7(deliveredLatencies, 0.99);
    const double missRatio = static_cast<double>(misses) /
                             static_cast<double>(measuredControlPackets);
    const uint64_t bulkDeliveredPackets =
        sink->GetMeasuredDeliveredPackets(FlowKind::BULK);
    const double bulkGoodputBps =
        static_cast<double>(sink->GetMeasuredDeliveredIpBytes(FlowKind::BULK)) * 8.0 /
        measurementDuration;
    double realizedMeanServiceBps = static_cast<double>(bottleneckBps);
    if (serviceMode == "alternating")
    {
        realizedMeanServiceBps = static_cast<double>(bottleneckBps) *
                                 IntegrateServiceFactor(measurementStart,
                                                        measurementEnd,
                                                        trafficStart,
                                                        servicePhaseSeconds,
                                                        serviceDwell,
                                                        serviceLowFactor,
                                                        serviceHighFactor) /
                                 measurementDuration;
    }

    std::ofstream summaryOutput(summaryPath, std::ios::out | std::ios::trunc);
    if (!summaryOutput)
    {
        throw std::runtime_error("cannot open summary CSV: " + summaryPath.string());
    }
    summaryOutput
        << "schema_version,ns3_version,seed,run,queue_mode,service_mode,target_rho,"
           "realized_offered_load,R,tauB_periods,bulk_on_periods,tauS_periods,"
           "service_low_factor,service_high_factor,control_period_s,deadline_s,"
           "warmup_control_packets,measured_control_packets,measurement_duration_s,"
           "nominal_bottleneck_bps,realized_mean_service_bps,access_bps,buffer_bytes,"
           "control_ip_bytes,sensor_ip_bytes,bulk_ip_bytes,target_control_bps,"
           "target_sensor_bps,target_bulk_bps,realized_control_bps,realized_sensor_bps,"
           "realized_bulk_bps,control_generated,control_source_send_ok,control_delivered,"
           "control_undelivered,control_p99_s,control_p99_over_T,control_deadline_misses,"
           "control_miss_ratio,bulk_generated,bulk_delivered,bulk_goodput_bps,"
           "bulk_phase_fraction,bulk_phase_s,service_phase_fraction,service_phase_s,"
           "drain_time_s,load_basis,packet_csv\n";
    summaryOutput << std::setprecision(17)
                  << "1,3.47," << seed << ',' << run << ',' << queueMode << ','
                  << serviceMode << ',' << rho << ',' << realizedOfferedLoad << ',' << pmr
                  << ',' << tauBPeriods << ',' << tauBPeriods / pmr << ','
                  << serviceDwellPeriods << ',' << serviceLowFactor << ','
                  << serviceHighFactor << ',' << controlPeriod << ',' << deadline << ','
                  << warmupControlPackets << ',' << measuredControlPackets << ','
                  << measurementDuration << ',' << bottleneckBps << ','
                  << realizedMeanServiceBps << ',' << accessBps << ',' << bufferBytes << ','
                  << controlIpBytes << ',' << sensorIpBytes << ',' << bulkIpBytes << ','
                  << targetControlBps << ',' << targetSensorBps << ',' << targetBulkBps << ','
                  << realizedControlBps << ',' << realizedSensorBps << ','
                  << realizedBulkBps << ',' << measuredControlGenerated << ','
                  << sourceAccepted << ',' << delivered << ','
                  << (measuredControlPackets - delivered) << ',' << CsvNumber(p99) << ','
                  << CsvNumber(p99 / controlPeriod) << ',' << misses << ',' << missRatio << ','
                  << measuredBulkGenerated << ',' << bulkDeliveredPackets << ','
                  << bulkGoodputBps << ',' << bulkPhaseFraction << ',' << bulkPhaseSeconds << ','
                  << servicePhaseFraction << ',' << servicePhaseSeconds << ',' << drainSeconds
                  << ",ip_packet_bits_over_nominal_mean_bottleneck_bps," << packetPath.string()
                  << '\n';
    summaryOutput.close();
    if (!summaryOutput)
    {
        throw std::runtime_error("failed while writing summary CSV: " + summaryPath.string());
    }

    std::cout << "completed: queue=" << queueMode << " service=" << serviceMode
              << " rho=" << rho << " R=" << pmr << " tauB/T=" << tauBPeriods
              << " P99/T=" << CsvNumber(p99 / controlPeriod)
              << " miss_ratio=" << missRatio << " delivered=" << delivered << '/'
              << measuredControlPackets << std::endl;

    Simulator::Destroy();
    return 0;
}

} // namespace

int
main(int argc, char* argv[])
{
    try
    {
        return RunScenario(argc, argv);
    }
    catch (const std::exception& error)
    {
        std::cerr << "ERROR: " << error.what() << std::endl;
        Simulator::Destroy();
        return 2;
    }
}


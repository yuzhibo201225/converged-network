// Reuse frozen packet/header/topology helpers, not the Python event engine.
#define main frozen_validation_entry
#include "burst-tail-validation.cc"
#undef main
#include <deque>

namespace {
struct SourceRecord {
    FlowKind flow; uint32_t id; double generated;
    double released{std::numeric_limits<double>::quiet_NaN()};
    bool dropped{false}; bool sent{false};
};
using PacketKey=std::pair<int,uint32_t>;

class AllSink : public Application {
public:
    std::map<PacketKey,double> received;
private:
    Ptr<Socket> socket;
    void StartApplication() override {
        socket=Socket::CreateSocket(GetNode(),UdpSocketFactory::GetTypeId());
        Require(socket->Bind(InetSocketAddress(Ipv4Address::GetAny(),kSinkPort))==0,"sink bind");
        socket->SetRecvCallback(MakeCallback(&AllSink::Read,this));
    }
    void Read(Ptr<Socket> s) {
        Address from;
        while (auto p=s->RecvFrom(from)) {
            ExperimentHeader h; Require(p->GetSize()>=h.GetSerializedSize(),"short packet");
            p->RemoveHeader(h);Require(h.IsValid(),"invalid header");
            auto key=PacketKey(static_cast<int>(h.GetFlow()),h.GetSequence());
            Require(received.emplace(key,Simulator::Now().GetSeconds()).second,"duplicate receive");
        }
    }
};

class FeedbackSource : public Application {
public:
    FlowKind flow; uint32_t ipBytes; Ipv4Address destination;
    std::vector<Emission> emissions; std::vector<SourceRecord> records;
    std::string shape{"none"}; double rho{},bias{},lag{},phase{},dwell{},reference{};
    double nominal{6000000},bucket{12000},capacity{1920000};
    double maxQueuedBits{0};
    bool Empty() const {return pending.empty();}
private:
    Ptr<Socket> socket;std::deque<size_t> pending;
    double tokens{0},last{0},rate{0};EventId wake;
    double RateAt(double t) const {
        if(shape=="fixed") return (rho-.03)*nominal;
        return (rho*(ServiceFactorAt(t-lag,reference,phase,dwell,.7,1.3)+bias)-.03)*nominal;
    }
    double NextBoundary(double t) const {
        if(shape!="feedback") return std::numeric_limits<double>::infinity();
        double position=std::fmod(t-lag-reference+phase,2*dwell);
        if(position<0) position+=2*dwell;
        double width=dwell-std::fmod(position,dwell);
        if(width<2e-9) width=dwell;
        return t+width;
    }
    void StartApplication() override {
        socket=Socket::CreateSocket(GetNode(),UdpSocketFactory::GetTypeId());
        Require(socket->Bind()==0,"source bind");
        socket->SetIpTos(flow==FlowKind::CONTROL?0xb8:0);
        Require(socket->Connect(InetSocketAddress(destination,kSinkPort))==0,"source connect");
        last=Simulator::Now().GetSeconds();tokens=bucket;
        rate=shape=="none"?0:RateAt(last);
        Require(shape=="none"||rate>0,"nonpositive refill");
        records.reserve(emissions.size());
        for (const auto& e:emissions) records.push_back({flow,e.sequence,Seconds(e.timeSeconds).GetSeconds()});
        for(size_t i=0;i<records.size();++i)
            Simulator::Schedule(Seconds(records[i].generated)-Simulator::Now(),&FeedbackSource::Generate,this,i);
    }
    void Update() {
        double now=Simulator::Now().GetSeconds();
        tokens=std::min(bucket,tokens+rate*(now-last));last=now;
        rate=RateAt(now+1e-9);Require(rate>0,"nonpositive refill");
    }
    void Send(size_t i) {
        auto& r=records[i];r.released=Simulator::Now().GetSeconds();
        ExperimentHeader h;h.Set(flow,r.id,Seconds(r.generated).GetNanoSeconds());
        auto p=Create<Packet>(ipBytes-kIpv4UdpHeaderBytes-h.GetSerializedSize());p->AddHeader(h);
        r.sent=socket->Send(p)==static_cast<int>(ipBytes-kIpv4UdpHeaderBytes);
    }
    void Generate(size_t i) {
        if(shape=="none") {Send(i);return;}
        Pump();
        double bits=ipBytes*8.;
        if(pending.empty()&&tokens+rate*1e-9>=bits) {tokens-=bits;Send(i);}
        else if((pending.size()+1)*bits>capacity+1e-3) records[i].dropped=true;
        else {pending.push_back(i);maxQueuedBits=std::max(maxQueuedBits,pending.size()*bits);}
        ScheduleWake();
    }
    void Pump() {
        if(wake.IsPending()) Simulator::Cancel(wake);
        Update();double bits=ipBytes*8.;
        while(!pending.empty()&&tokens+rate*1e-9>=bits) {
            // Keep sub-nanosecond token debt: clipping it on every packet accumulates drift.
            size_t i=pending.front();pending.pop_front();tokens-=bits;Send(i);
        }
        ScheduleWake();
    }
    void ScheduleWake() {
        if(wake.IsPending()) Simulator::Cancel(wake);
        double now=Simulator::Now().GetSeconds();
        // Wake at every delayed transition even when empty; never integrate a future rate.
        double next=NextBoundary(now);
        if(!pending.empty()) next=std::min(next,now+std::max(1e-9,(ipBytes*8.-tokens)/rate));
        if(std::isfinite(next)) wake=Simulator::Schedule(Seconds(std::max(1e-9,next-now)),&FeedbackSource::Pump,this);
    }
};

int RunFeedback(int argc,char** argv) {
    double rho=.95,pmr=3,tauB=8,tauS=8,bias=0,lagPeriods=.5,sourceCapacity=16;
    uint32_t seed=20261012,measured=10000,warm=256;uint64_t run=1;
    std::string queue="fifo",shape="feedback",summaryCsv="feedback-summary.csv",packetCsv="feedback-packets.csv";
    CommandLine cmd(__FILE__);
    cmd.AddValue("rho","IP generated mean load",rho);cmd.AddValue("R","source PMR",pmr);
    cmd.AddValue("tauB","bulk full cycle/T",tauB);cmd.AddValue("tauS","service dwell/T",tauS);
    cmd.AddValue("bias","additive capacity factor bias",bias);cmd.AddValue("lag","feedback lag/T",lagPeriods);
    cmd.AddValue("capacity","source queued work/T",sourceCapacity);cmd.AddValue("shape","none/fixed/feedback",shape);
    cmd.AddValue("queue","fifo/priority/fifo_packet/fq_codel",queue);
    cmd.AddValue("seed","phase seed",seed);cmd.AddValue("run","paired phase run",run);
    cmd.AddValue("measured","measured control packets",measured);cmd.AddValue("warm","warmup periods",warm);
    cmd.AddValue("summaryCsv","new summary path",Callback<bool,const std::string&>([&](const std::string& v){summaryCsv=v;return !v.empty();}));
    cmd.AddValue("packetCsv","new all-flow packet path",Callback<bool,const std::string&>([&](const std::string& v){packetCsv=v;return !v.empty();}));
    cmd.Parse(argc,argv);
    Require(rho>.03&&rho<=1&&pmr>=1&&std::isfinite(bias)&&lagPeriods>=0&&sourceCapacity>=.1,"invalid parameters");
    Require(shape=="none"||shape=="fixed"||shape=="feedback","invalid shaper");
    Require(queue=="fifo"||queue=="priority"||queue=="fifo_packet"||queue=="fq_codel","invalid qdisc");
    Require(tauB>0&&tauS>0&&IsIntegerRatio(warm,tauB)&&IsIntegerRatio(measured,tauB)&&
        IsIntegerRatio(warm,2*tauS)&&IsIntegerRatio(measured,2*tauS)&&warm%2==0&&measured%2==0,"non-whole measurement cycles");
    Require(shape!="feedback"||rho*(.7+bias)>.03,"nonpositive feedback rate");
    Require(summaryCsv!=packetCsv,"same output paths");EnsureNewOutputPath(summaryCsv);EnsureNewOutputPath(packetCsv);
    const double T=.02,start=1.,begin=start+warm*T,end=begin+measured*T,stop=end+6.;
    const uint64_t nominal=6000000,accessRate=100000000;
    Require(pmr*(rho-.03)*nominal<.95*accessRate,"access overload");
    Require(sourceCapacity/((shape=="feedback"?rho*(.7+bias):rho)-.03)*T+1.<6.,"insufficient source drain");
    RngSeedManager::SetSeed(seed);RngSeedManager::SetRun(run);
    double bulkPhase=PairedUniform01(seed,run,0x42554c4bULL),lattice=1-PairedUniform01(seed,run,0x4c415454ULL);
    double servicePhase=PairedUniform01(seed,run,0x53455256ULL);
    std::array<std::vector<Emission>,3> arrivals{
        BuildPeriodicEmissions(start,T,warm+measured),BuildPeriodicEmissions(start,2*T,(warm+measured)/2),
        BuildBurstEmissions(start,end,start,bulkPhase*tauB*T,tauB*T,tauB*T/pmr,
                            pmr*(rho-.03)*nominal,1500,lattice)};
    NodeContainer nodes;nodes.Create(5);InternetStackHelper internet;internet.Install(nodes);
    PointToPointHelper access;access.SetDeviceAttribute("DataRate",DataRateValue(DataRate(accessRate)));
    access.SetChannelAttribute("Delay",TimeValue(MicroSeconds(50)));access.SetQueue("ns3::DropTailQueue","MaxSize",StringValue("20p"));
    std::array<NetDeviceContainer,3> links;
    for(int i=0;i<3;++i) links[i]=access.Install(nodes.Get(i),nodes.Get(3));
    PointToPointHelper bottleneck;bottleneck.SetDeviceAttribute("DataRate",DataRateValue(DataRate(nominal)));
    bottleneck.SetChannelAttribute("Delay",TimeValue(MicroSeconds(200)));bottleneck.SetQueue("ns3::DropTailQueue","MaxSize",StringValue("1p"));
    auto bottleneckDevices=bottleneck.Install(nodes.Get(3),nodes.Get(4));TrafficControlHelper tc;
    if(queue=="fifo"||queue=="fifo_packet") tc.SetRootQueueDisc("ns3::FifoQueueDisc","MaxSize",QueueSizeValue(QueueSize(queue=="fifo"?"150000B":"100p")));
    else if(queue=="priority") tc.SetRootQueueDisc("ns3::ResearchStrictPriorityQueueDisc","MaxSize",QueueSizeValue(QueueSize("150000B")));
    else tc.SetRootQueueDisc("ns3::FqCoDelQueueDisc","MaxSize",QueueSizeValue(QueueSize("100p")),
        "UseEcn",BooleanValue(false),"Target",StringValue("5ms"),"Interval",StringValue("100ms"),"Perturbation",UintegerValue(0));
    tc.Install(bottleneckDevices.Get(0));Ipv4AddressHelper address;
    for(int i=0;i<3;++i) {std::string subnet="10.2."+std::to_string(i+1)+".0";address.SetBase(subnet.c_str(),"255.255.255.0");address.Assign(links[i]);}
    address.SetBase("10.2.4.0","255.255.255.0");auto interfaces=address.Assign(bottleneckDevices);
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    ConfigureAlternatingService(DynamicCast<PointToPointNetDevice>(bottleneckDevices.Get(0)),start,
        servicePhase*2*tauS*T,tauS*T,nominal,.7,1.3,stop);
    auto sink=CreateObject<AllSink>();nodes.Get(4)->AddApplication(sink);sink->SetStartTime(Seconds(0));
    std::array<Ptr<FeedbackSource>,3> sources;const std::array<uint32_t,3> sizes{150,600,1500};
    for(int i=0;i<3;++i) {
        auto s=CreateObject<FeedbackSource>();sources[i]=s;s->flow=static_cast<FlowKind>(i+1);s->ipBytes=sizes[i];
        s->destination=interfaces.GetAddress(1);s->emissions=std::move(arrivals[i]);s->shape=i==2?shape:"none";
        s->rho=rho;s->bias=bias;s->lag=lagPeriods*T;s->phase=servicePhase*2*tauS*T;s->dwell=tauS*T;s->reference=start;
        s->nominal=nominal;s->bucket=.1*nominal*T;s->capacity=sourceCapacity*nominal*T;
        nodes.Get(i)->AddApplication(s);s->SetStartTime(Seconds(start));
    }
    Simulator::Stop(Seconds(stop));Simulator::Run();Require(sources[2]->Empty(),"source cohort not drained");
    std::ofstream packets(packetCsv);packets<<std::setprecision(17);
    packets<<"flow,id,measured,generated_s,released_s,received_s,source_drop,source_send_ok,status,latency_T,source_wait_T\n";
    std::array<uint64_t,3> generated{},delivered{},sourceDrops{};std::array<std::vector<double>,3> latencies;
    uint64_t misses=0;double admittedBits=0;
    for(int i=0;i<3;++i) for(const auto& r:sources[i]->records) {
        auto it=sink->received.find(PacketKey(i+1,r.id));bool recv=it!=sink->received.end();
        bool cohort=r.generated>=begin-kTolerance&&r.generated<end-kTolerance;
        if(std::isfinite(r.released)&&r.released>=begin-kTolerance&&r.released<end-kTolerance&&r.sent) admittedBits+=sizes[i]*8.;
        double latency=recv?(it->second-r.generated)/T:std::numeric_limits<double>::quiet_NaN();
        std::string status=r.dropped?"source_drop":(!r.sent?"source_send_failed":(recv?"delivered":"undelivered_after_drain"));
        packets<<i+1<<','<<r.id<<','<<cohort<<','<<r.generated<<','<<CsvNumber(r.released)<<','
            <<(recv?CsvNumber(it->second):"")<<','<<r.dropped<<','<<r.sent<<','<<status<<','<<CsvNumber(latency)<<','
            <<CsvNumber((r.released-r.generated)/T)<<'\n';
        if(cohort) {++generated[i];sourceDrops[i]+=r.dropped;if(recv){++delivered[i];latencies[i].push_back(latency);}
            if(i==0&&(!recv||latency>=1)) ++misses;}
    }
    packets.close();Require(bool(packets),"packet write failed");Require(generated[0]==measured,"control cohort mismatch");
    double generatedRho=(generated[0]*150.+generated[1]*600.+generated[2]*1500.)*8/(measured*T*nominal);
    std::ofstream summary(summaryCsv);summary<<std::setprecision(17);
    summary<<"rho,R,tauB,tauS,shape,queue,bias,lag,capacity,seed,run,T,warm,measured,begin_s,end_s,stop_s,bulk_phase_fraction,lattice_fraction,service_phase_fraction,generated_rho,admitted_rho,control_generated,control_delivered,control_p99_T,control_miss_ratio,bulk_generated,bulk_delivered,bulk_source_drop,bulk_p99_T,source_max_work,nominal_bps\n";
    summary<<rho<<','<<pmr<<','<<tauB<<','<<tauS<<','<<shape<<','<<queue<<','<<bias<<','<<lagPeriods<<','<<sourceCapacity
        <<','<<seed<<','<<run<<','<<T<<','<<warm<<','<<measured<<','<<begin<<','<<end<<','<<stop<<','<<bulkPhase<<','<<lattice<<','<<servicePhase
        <<','<<generatedRho<<','<<admittedBits/(measured*T*nominal)<<','<<generated[0]<<','<<delivered[0]<<','<<CsvNumber(PercentileR7(latencies[0],.99))
        <<','<<double(misses)/measured<<','<<generated[2]<<','<<delivered[2]<<','<<sourceDrops[2]<<','<<CsvNumber(PercentileR7(latencies[2],.99))
        <<','<<sources[2]->maxQueuedBits/(nominal*T)<<','<<nominal<<'\n';
    summary.close();Require(bool(summary),"summary write failed");
    std::cout<<"complete "<<shape<<"/"<<queue<<" rho="<<rho<<" bias="<<bias<<" control P99/T="<<PercentileR7(latencies[0],.99)<<std::endl;
    Simulator::Destroy();return 0;
}
}

int main(int argc,char** argv) {
    try {return RunFeedback(argc,argv);}
    catch(const std::exception& e) {std::cerr<<"ERROR: "<<e.what()<<std::endl;Simulator::Destroy();return 2;}
}

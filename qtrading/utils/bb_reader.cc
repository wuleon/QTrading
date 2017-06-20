// Contents Copyright Shanghai ShanCe Technologies Company Ltd. All Rights Reserved.


// bbreader: a copy of dfview to help you write utils along with your  strategy


#include <iostream>
#include <list>
#include <vector>

#include <boost/foreach.hpp>

#include <bb/core/env.h>
#include <bb/core/Error.h>
#include <bb/core/Log.h>
#include <bb/core/messages.h>
#include <bb/core/program_options.h>
#include <bb/core/protobuf/ProtoBufMsg.h>

#include <bb/io/CFile.h>
#include <bb/io/DFStream.h>
#include <bb/io/SendTransport.h>
#include <bb/io/ZByteSink.h>

void usage(const boost::program_options::options_description& options)
{
    std::cerr <<
            "\n"
            "usage:  bbreader [OPTION...] datafile[+delay]..." "\n"
            "\n"
            "      Dumps the messages of binary datafiles to stdout." "\n"
            "      The contents of all the files are put in time order.  You can specify a fixed delay" "\n"
            "      by appending +delay to any filename.  So, bbreader info.20060501+1.0 would read in " "\n"
            "      info.20060501 and add 1 second to each message." "\n"
            "\n"
            "      If both -x and -t are specified, the trim happens first, and then the tail. So -x 10 -t 3" "\n"
            "      on a file 100 messages will cut off 10 messages, and then give you the remaining last 3." "\n"
            "\n"
            "      if datafile is '-', stdin will be read." "\n"
            "\n"
            << options;
}


// takes STR, and pulls out the base fname and delay time if there is one.
// returns <filename, delay>
// If no delay is specified, returns a zero delay.
boost::tuple<std::string, bb::ptime_duration_t> extract_fname(std::string str)
{
    std::string::size_type pos = str.find('+');
    bb::ptime_duration_t delay;
    if(pos != std::string::npos)
    {
        std::string tmStr = str.substr(pos+1);
        delay = boost::lexical_cast<bb::ptime_duration_t>(tmStr);
        str.erase(pos);
    }

    return boost::make_tuple(str, delay);
}


class TailedOutput : public bb::ISendTransport
{
public:
    typedef std::list<const bb::Msg *> msg_queue;

    TailedOutput(const bb::ISendTransportPtr &_out, unsigned int _num)
        : out(_out), num(_num) { }

    virtual ~TailedOutput()
    {
        for (msg_queue::iterator p = buf.begin(); p != buf.end(); p++) {
            out->send(*p);
            delete *p;
        }
    }

    virtual void send(const bb::Msg *m)
    {
        buf.push_back(m->clone());
        while (buf.size() > num) {
            delete buf.front();
            buf.pop_front();
        }
    }

private:
    bb::ISendTransportPtr out;
    unsigned int num;
    msg_queue buf;
};

class TrimmedOutput : public bb::ISendTransport
{
public:
    typedef std::list<const bb::Msg *> msg_queue;

    TrimmedOutput(const bb::ISendTransportPtr &_out, unsigned int _num)
        : out(_out), num(_num) { }

    virtual ~TrimmedOutput()
    {
        for (msg_queue::iterator p = buf.begin(); p != buf.end(); p++)
            delete *p;
    }

    virtual void send(const bb::Msg *m)
    {
        buf.push_back(m->clone());
        while (buf.size() > num) {
            out->send(buf.front());
            delete buf.front();
            buf.pop_front();
        }
    }

private:
    bb::ISendTransportPtr out;
    unsigned int num;
    msg_queue buf;
};


class MessageHandler : public bb::IMStreamCallback
{
public:
    MessageHandler(const bb::DFStreamMplexPtr &stream, unsigned int headLen, const bb::ISendTransportPtr &out,
            const bb::timeval_t &start_tv, const bb::timeval_t &end_tv)
        : m_stream(stream)
        , m_headLen(headLen)
        , m_out(out)
        , m_messagesSeen(0)
        , m_startTv(start_tv)
        , m_endTv(end_tv)
    {
    }

    typedef std::map<const bb::IHistMStream*, std::string> StreamNames;
    void setStreamNames(const StreamNames& stream_names) { m_streamNames = stream_names; }

    virtual void onMessage(const bb::Msg &msg)
    {
        if (m_streamNames)
        {
            const bb::IHistMStream* source = m_stream->getOrigin().get();
            StreamNames::const_iterator it = m_streamNames->find(source);
            BB_THROW_EXASSERT(it != m_streamNames->end(), "failed to find name for stream");
            std::cout << "file:" << it->second << ' ';
        }

        if (m_headLen > 0 && m_messagesSeen >= m_headLen)
            m_stream->stop();
        else if (msg.hdr->time_sent >= m_endTv)
            m_stream->stop();
        else if (msg.hdr->time_sent >= m_startTv)
        {
            m_out->send(&msg);
            ++m_messagesSeen;
        }
    }

    bb::DFStreamMplexPtr m_stream;
    boost::optional<StreamNames> m_streamNames;
    unsigned int m_headLen;
    bb::ISendTransportPtr m_out;
    long long m_messagesSeen;
    bb::timeval_t m_startTv, m_endTv;
};


int main(int argc, char **argv)
{
    bb::setLogger("bbreader", std::cerr);
    bb::default_init();

    bb::source_t::setOutputFormat( bb::source_t::FORMAT_SHORT );

    std::vector<std::string> inputs;
    bool help;
    bool no_output;
    bool binary_dgram;
    bool print_json;
    bool print_names;
    bool machine_mtypes;
    bool count;
    bool linear_only; // avoid use of DFSearchReader
    bool ignore_file_errors;

    unsigned int head_len = 0;
    unsigned int tail_len = 0;
    unsigned int trim_len = 0;
    std::string start_tv_str;
    std::string end_tv_str;
    std::string output_filename;
    std::string proto_file_str;
    bool compress_output;

    namespace po = boost::program_options;

    bb::options_description options("options");
    options.add_options()
        ("quiet"          ",q", po::bool_switch(&no_output),       "don't print messages (for benchmarking)")
        ("count"          ",n", po::bool_switch(&count),           "print out the number of messages read")
        ("binary"         ",D", po::bool_switch(&binary_dgram),    "output binary datagrams")
        ("compress"       ",Z", po::bool_switch(&compress_output), "gzip output")
        ("start-date"     ",s", po::value      (&start_tv_str),    "timeval to start printing from")
        ("end-date"       ",e", po::value      (&end_tv_str),      "timeval to stop printing at")
        ("head"           ",h", po::value      (&head_len),        "only print the first N messages")
        ("tail"           ",t", po::value      (&tail_len),        "only output the last N messages")
        ("trim"           ",x", po::value      (&trim_len),        "trim the last N messages")
        ("output-file"    ",o", po::value      (&output_filename), "output to specified filename")
        ("protobuf-file"  ",P", po::value      (&proto_file_str),  "import protobuf definition from specified filename")
        ("linear-search"  ",l", po::bool_switch(&linear_only),     "only use linear search (needed for unsorted files)")
        ("json"           ",J", po::bool_switch(&print_json),      "output JSON")
        ("with-filename"  ",N", po::bool_switch(&print_names),     "print source filename before each line")
        ("numeric-mtypes" ",M", po::bool_switch(&machine_mtypes),  "print mtypes as integers")
        ("ignore-file-errors" , po::bool_switch(&ignore_file_errors),  "process will not return error if a file-related error is encountered")
        ("help",                po::bool_switch(&help),            "display this help")
        ;

    bb::options_description hidden_options;
    hidden_options.add_options()
        ("input", po::value(&inputs), "")
        ;

    po::positional_options_description positional_options;
    positional_options.add("input", -1/*unlimited*/);

    po::variables_map vm;
    try
    {
        po::store(po::command_line_parser(argc, argv).
                options(po::options_description().add(options).add(hidden_options)).
                positional(positional_options).run(), vm);
    }
    catch (const std::exception& ex)
    {
        std::cerr << "error: " << ex.what() << std::endl;
        usage(options);
        return EXIT_FAILURE;
    }

    po::notify(vm);

    if (help)
    {
        usage(options);
        return EXIT_SUCCESS;
    }

    if( !proto_file_str.empty() )
    {
        bb::ProtoBufMsgBase::addMessageTypeFromProtoFile( proto_file_str );
    }

    bb::timeval_t start_tv = start_tv_str.empty() ? bb::timeval_t::earliest : bb::timeval_t::make_time(start_tv_str);
    bb::timeval_t   end_tv =   end_tv_str.empty() ? bb::timeval_t::latest   : bb::timeval_t::make_time(  end_tv_str);

    if (start_tv >= end_tv)
    {
        std::cerr << "start_tv is after end_tv" << std::endl << std::endl;
        usage(options);
        return EXIT_FAILURE;
    }

    if (inputs.empty())
    {
        usage(options);
        return EXIT_FAILURE;
    }

    if (machine_mtypes)
        bb::MsgHdr::print_human_readable_mtype = false;

    bb::DFStreamMplexPtr dfm(new bb::DFStreamMplex());
    MessageHandler::StreamNames stream_names;

    BOOST_FOREACH(const std::string& input, inputs) {
        try {
            std::string filename;
            bb::ptime_duration_t delay;
            boost::tie(filename, delay) = extract_fname(input);
            bool isGz = filename.substr(filename.length() - std::min(size_t(3), filename.length())) == ".gz";
            bb::HistMStreamPtr df;
            if (filename == "-")
            {
                df.reset( new bb::DFReader(bb::ByteSourcePtr(new bb::CFile(stdin, "stdin"))) );
            }
            else if (start_tv == bb::timeval_t::earliest || linear_only)
            {
                df.reset( new bb::SingleDFStream(filename, isGz) );
            }
            else
            {
                bb::CFilePtr file(new bb::CFile(filename.c_str(), "r", bb::CFile::OPEN, 32*1024));
                bb::DFSearchReader* reader(new bb::DFSearchReader(boost::make_tuple(file, isGz, bb::source_t())));
                
                reader->search(start_tv);
                df.reset(reader);
            }
            if (delay == bb::ptime_duration_t())
                dfm->add(df);
            else
                dfm->add(boost::make_shared<bb::FixedDelayDFStream> (df, delay));

            if (print_names)
            {
                bool inserted = stream_names.insert(std::make_pair(df.get(), filename)).second;
                BB_THROW_EXASSERT_SS(inserted, "failed to insert stream name: " << filename);
            }
        } catch (const std::exception &e) {
            LOG_WARN << "error: " << e.what() << bb::endl;
        }
    }

    bool file_error = false;

    bb::ISendTransportPtr out;
    bb::ByteSinkPtr output_sink;

    if (!output_filename.empty()) {
        if (bb::CFile::exists(output_filename.c_str())) {
            std::cerr << "error: output file exists: " << output_filename << std::endl;
            return EXIT_FAILURE;
        }
        bb::CFilePtr fout(new bb::CFile(output_filename.c_str(), "w"));
        fout->open();
        output_sink = fout;
    }
    else
        output_sink.reset(new bb::OStreamByteSink(std::cout));

    if( compress_output )
        output_sink.reset( new bb::ZByteSink( output_sink ) );

    if (no_output)
        out.reset(new bb::DevNullSendTransport());
    else if (binary_dgram)
        out.reset(new bb::DGramWriteTransport(output_sink));
    else if (print_json)
        out.reset(new bb::JsonWriteTransport(output_sink));
    else
        out.reset(new bb::TextWriteTransport(output_sink));

    if (tail_len > 0)
        out.reset(new TailedOutput(out, tail_len));

    if (trim_len > 0)
        out.reset(new TrimmedOutput(out, trim_len));

    MessageHandler h(dfm, head_len, out, start_tv, end_tv);
    if (print_names && !no_output && !binary_dgram)
        h.setStreamNames(stream_names);

    try {
        dfm->run(&h);
    } catch(const std::exception &e) {
        if( !no_output) LOG_WARN << e.what() << bb::endl;
        file_error = true;
    }

    if (count)
        std::cerr << "read " << h.m_messagesSeen << " messages" << std::endl;

    file_error = ignore_file_errors ? false : file_error;
    return file_error ? EXIT_FAILURE : EXIT_SUCCESS;
}
